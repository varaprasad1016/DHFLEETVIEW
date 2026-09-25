"""Invoicing, for the super administrator only.

Which customers are billed, what they are charged, and every invoice that has
gone out. Nothing here is visible to a customer: they receive their own invoice
by email and see nothing of anyone else's.

GET    /api/billing/overview            accounts, rates, and what is still missing
PUT    /api/billing/accounts/{user_id}  set up or change how an account is billed
GET    /api/billing/invoices            every invoice issued
GET    /api/billing/invoices/{id}/pdf   one invoice as the customer received it
POST   /api/billing/preview             what an account would be charged, without issuing
POST   /api/billing/run                 raise the drafts for a month
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_manager
from app.config import settings
from app.database import get_session
from app.models.billing import BillingAccount, Invoice, InvoiceLine
from app.services import auth, invoice_pdf, invoicing, mailer, modules
from app.services.auth import Principal

logger = logging.getLogger("tacho.invoices")

router = APIRouter(prefix="/api/billing", tags=["billing"])
# Downloads go through here. The phone's own download handler fetches the file
# itself, with no session cookie of ours, so these links carry their own proof.
public_router = APIRouter(prefix="/invoices", tags=["billing"])

LINK_MINUTES = 15


def _signature(invoice_id: str, expires: int) -> str:
    """Proof that we issued this link, and when it stops working."""
    message = f"{invoice_id}:{expires}".encode()
    digest = hmac.new(settings.jwt_secret.encode(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _require_super(principal: Principal) -> None:
    if not modules.is_super_admin(principal):
        raise HTTPException(status_code=403, detail="Only a super administrator can see invoicing.")


def _account_json(account: BillingAccount) -> dict:
    return {
        "user_id": account.user_id, "name": account.name,
        "account_email": account.account_email, "invoicing_email": account.invoicing_email,
        "send_to": account.send_to, "started_on": account.started_on.isoformat(),
        "active": account.active,
        "rates": {"live": _number(account.rate_live),
                  "tacho": _number(account.rate_tacho)},
        "notes": account.notes,
    }


def _number(value) -> float | None:
    return float(value) if value is not None else None


def _invoice_json(invoice: Invoice) -> dict:
    return {
        "id": str(invoice.id), "number": invoice.number, "account": invoice.account_name,
        "user_id": invoice.user_id,
        "period_start": invoice.period_start.isoformat(),
        "period_end": invoice.period_end.isoformat(),
        "period": invoice_pdf.invoice_period(invoice),
        "issued_on": invoice.issued_on.isoformat(),
        "net": float(invoice.net), "vat": float(invoice.vat), "total": float(invoice.total),
        "status": invoice.status, "sent_to": invoice.sent_to,
        "sent_at": invoice.sent_at.isoformat() if invoice.sent_at else None,
        "detail": invoice.detail,
    }


@router.get("/overview")
async def overview(principal: Principal = Depends(require_manager),
                   session: AsyncSession = Depends(get_session)):
    """Who is billed, what they pay, and anything stopping invoices going out."""
    _require_super(principal)
    accounts = (await session.execute(
        select(BillingAccount).order_by(BillingAccount.name))).scalars().all()

    # Every account on the platform, so one can be picked up for billing.
    users = await auth.traccar_get(principal, "/api/users") or []
    billed = {a.user_id for a in accounts}
    candidates = [{"id": u["id"], "name": u.get("name") or u.get("email"),
                   "email": u.get("email")}
                  for u in users if not u.get("administrator") and u["id"] not in billed]

    return {
        "accounts": [_account_json(a) for a in accounts],
        "candidates": sorted(candidates, key=lambda c: (c["name"] or "").lower()),
        "standard_rates": {k: float(v) for k, v in invoicing.standard_rates().items()},
        "package_names": dict(invoicing.billing.PACKAGE_NAMES),
        "vat_rate": settings.invoice_vat_rate,
        "every_months": invoicing.every_months(),
        "auto_send": settings.invoice_auto_send,
        "company": {"name": settings.company_name, "address": settings.company_address,
                    "vat_number": settings.company_vat_number},
        "not_ready": invoicing.not_ready(),
    }


@router.put("/accounts/{user_id}")
async def set_account(user_id: int, body: dict = Body(...),
                      principal: Principal = Depends(require_manager),
                      session: AsyncSession = Depends(get_session)):
    """Start billing an account, or change how it is billed."""
    _require_super(principal)
    account = (await session.execute(
        select(BillingAccount).where(BillingAccount.user_id == user_id))).scalar_one_or_none()

    user = await auth.traccar_get(principal, f"/api/users/{user_id}")
    if user is None and account is None:
        raise HTTPException(status_code=404, detail="There is no such account.")

    started = body.get("started_on")
    if account is None:
        if not started:
            raise HTTPException(status_code=400,
                                detail="A start date is needed: it decides the first invoice.")
        account = BillingAccount(user_id=user_id, name=user.get("name") or user.get("email"),
                                 account_email=user.get("email"),
                                 started_on=date.fromisoformat(started))
        session.add(account)
    else:
        if started:
            account.started_on = date.fromisoformat(started)
        if user:
            account.account_email = user.get("email")
            account.name = user.get("name") or account.name

    if "invoicing_email" in body:
        account.invoicing_email = (body.get("invoicing_email") or "").strip() or None
    if "active" in body:
        account.active = bool(body["active"])
    if "notes" in body:
        account.notes = (body.get("notes") or "").strip() or None
    for item in invoicing.billing.PACKAGES:
        if item in (body.get("rates") or {}):
            value = (body["rates"] or {})[item]
            setattr(account, f"rate_{item}",
                    Decimal(str(value)) if value not in (None, "") else None)

    await session.commit()
    await session.refresh(account)
    return _account_json(account)


@router.post("/preview")
async def preview(body: dict = Body(...), principal: Principal = Depends(require_manager),
                  session: AsyncSession = Depends(get_session)):
    """What an account would be charged for a period. Nothing is issued or sent."""
    _require_super(principal)
    account = (await session.execute(
        select(BillingAccount).where(
            BillingAccount.user_id == int(body["user_id"])))).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="That account is not set up for billing.")

    months = int(body.get("months") or invoicing.every_months())
    closed = invoicing.billing.last_closed_period(date.today(), months)
    built = await invoicing.build_for(principal, account, int(body.get("year") or closed[0]),
                                      int(body.get("month") or closed[1]), session, months)
    return {
        "account": account.name, "period": built.period,
        "lines": [{"vehicle": line.vehicle, "item": line.item,
                   "description": line.describe(), "rate": float(line.rate),
                   "days": line.days, "days_in_month": line.days_in_month,
                   "amount": float(line.amount)} for line in built.lines],
        "net": float(built.net), "vat": float(built.vat), "total": float(built.total),
    }


@router.get("/invoices")
async def list_invoices(limit: int = Query(100, ge=1, le=500),
                        user_id: int | None = None,
                        principal: Principal = Depends(require_manager),
                        session: AsyncSession = Depends(get_session)):
    _require_super(principal)
    query = select(Invoice).order_by(Invoice.issued_on.desc(), Invoice.number.desc()).limit(limit)
    if user_id:
        query = query.where(Invoice.user_id == user_id)
    rows = (await session.execute(query)).scalars().all()
    return {"invoices": [_invoice_json(i) for i in rows]}


@router.get("/invoices/{invoice_id}")
async def one_invoice(invoice_id: str, principal: Principal = Depends(require_manager),
                      session: AsyncSession = Depends(get_session)):
    """One invoice and its lines, for showing on screen.

    The PDF is the thing the customer receives, but a phone cannot display one
    inside a page, so the screen draws the invoice from this instead.
    """
    _require_super(principal)
    invoice = await session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="No such invoice.")
    lines = (await session.execute(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)
        .order_by(InvoiceLine.position))).scalars().all()
    account = (await session.execute(
        select(BillingAccount).where(
            BillingAccount.user_id == invoice.user_id))).scalar_one_or_none()
    return {
        **_invoice_json(invoice),
        "customer_email": account.send_to if account else None,
        "company": {"name": settings.company_name, "address": settings.company_address,
                    "vat_number": settings.company_vat_number,
                    "number": settings.company_number,
                    "terms": settings.invoice_payment_terms},
        # Grouped by service, exactly as the customer's PDF reads. The
        # per-vehicle workings are kept below for anyone checking a figure.
        "lines": [{"description": charge["description"], "rate": float(charge["rate"]),
                   "quantity": charge["quantity"], "unit": float(charge["unit"]),
                   "amount": float(charge["amount"])}
                  for charge in invoice_pdf.group(lines)],
        "vehicles": [{"description": line.description, "rate": float(line.rate),
                      "days": line.days, "days_in_month": line.days_in_month,
                      "amount": float(line.amount)} for line in lines],
    }


@router.post("/invoices/{invoice_id}/send")
async def send_invoice(invoice_id: str, body: dict = Body(default={}),
                       principal: Principal = Depends(require_manager),
                       session: AsyncSession = Depends(get_session)):
    """Email one invoice to the customer, with the PDF attached.

    Refuses while anything is still a placeholder: a wrong figure or a
    placeholder VAT number reaching a customer is not something that can be
    taken back.
    """
    _require_super(principal)
    missing = invoicing.not_ready()
    if missing and not body.get("anyway"):
        raise HTTPException(status_code=400,
                            detail="Not ready to send: " + "; ".join(missing))

    invoice = await session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="No such invoice.")

    try:
        to = await invoicing.email_invoice(session, invoice, body.get("to"),
                                           automatic=False)
    except mailer.MailError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info("%s emailed %s to %s", principal.email, invoice.number, to)
    return {"number": invoice.number, "sent_to": to,
            "sent_at": invoice.sent_at.isoformat() if invoice.sent_at else None}


@router.post("/send-all")
async def send_all(body: dict = Body(default={}),
                   principal: Principal = Depends(require_manager),
                   session: AsyncSession = Depends(get_session)):
    """Email every invoice still waiting to go out.

    The same thing the quarterly run does, for when it is being done by hand -
    after a mail server outage, say, or the first time round.
    """
    _require_super(principal)
    missing = invoicing.not_ready()
    if missing and not body.get("anyway"):
        raise HTTPException(status_code=400,
                            detail="Not ready to send: " + "; ".join(missing))

    query = select(Invoice).where(Invoice.status != "sent").order_by(Invoice.number)
    if body.get("user_id"):
        query = query.where(Invoice.user_id == int(body["user_id"]))
    sent, failed = [], []
    for invoice in (await session.execute(query)).scalars().all():
        try:
            to = await invoicing.email_invoice(session, invoice, automatic=False)
            sent.append({"number": invoice.number, "account": invoice.account_name, "to": to})
        except mailer.MailError as exc:
            failed.append({"number": invoice.number, "account": invoice.account_name,
                           "why": str(exc)})
    logger.info("%s sent %d invoice(s) by hand", principal.email, len(sent))
    return {"sent": sent, "failed": failed}


@router.get("/invoices/{invoice_id}/link")
async def download_link(invoice_id: str, principal: Principal = Depends(require_manager),
                        session: AsyncSession = Depends(get_session)):
    """A link the phone itself can fetch, good for a few minutes.

    Saving a file from inside the app cannot go through our own session: the
    handler that does the saving makes its own request and carries none of our
    cookies. So the link proves itself instead, and expires quickly.
    """
    _require_super(principal)
    invoice = await session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="No such invoice.")
    expires = int((datetime.now(timezone.utc) + timedelta(minutes=LINK_MINUTES)).timestamp())
    return {"url": f"/tacho/invoices/{invoice.id}/{expires}/"
                   f"{_signature(str(invoice.id), expires)}/{invoice.number}.pdf",
            "expires_in_minutes": LINK_MINUTES}


@public_router.get("/{invoice_id}/{expires}/{signature}/{filename}")
async def signed_pdf(invoice_id: str, expires: int, signature: str, filename: str,
                     session: AsyncSession = Depends(get_session)):
    """One invoice, to whoever holds a link we issued and has not sat on it."""
    if not hmac.compare_digest(signature, _signature(invoice_id, expires)):
        raise HTTPException(status_code=403, detail="That link is not valid.")
    if datetime.now(timezone.utc).timestamp() > expires:
        raise HTTPException(status_code=403, detail="That link has expired. Open it again.")

    invoice = await session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="No such invoice.")
    lines = (await session.execute(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)
        .order_by(InvoiceLine.position))).scalars().all()
    account = (await session.execute(
        select(BillingAccount).where(
            BillingAccount.user_id == invoice.user_id))).scalar_one_or_none()
    pdf = invoice_pdf.render(invoice, lines, customer_name=invoice.account_name,
                             customer_email=account.send_to if account else None)
    # Named in the path as well as the header: a phone's download handler reads
    # whichever it likes, and both say .pdf.
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{invoice.number}.pdf"'})


@router.get("/invoices/{invoice_id}/pdf")
async def invoice_pdf_file(invoice_id: str, download: bool = False,
                           principal: Principal = Depends(require_manager),
                           session: AsyncSession = Depends(get_session)):
    """The invoice exactly as the customer received it.

    Shown in the browser by default so it can be checked at a glance;
    `?download=1` saves it instead, for sending on or filing.
    """
    _require_super(principal)
    invoice = await session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="No such invoice.")
    lines = (await session.execute(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)
        .order_by(InvoiceLine.position))).scalars().all()
    account = (await session.execute(
        select(BillingAccount).where(
            BillingAccount.user_id == invoice.user_id))).scalar_one_or_none()
    pdf = invoice_pdf.render(invoice, lines, customer_name=invoice.account_name,
                             customer_email=account.send_to if account else None)
    disposition = "attachment" if download else "inline"
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'{disposition}; filename="{invoice.number}.pdf"'})


@router.post("/run")
async def run_period(body: dict = Body(default={}),
                     principal: Principal = Depends(require_manager),
                     session: AsyncSession = Depends(get_session)):
    """Raise a billing period's invoices as drafts. Sending is a separate step.

    Defaults to the period that has most recently closed, which is what the
    quarterly run raises by itself. `year`/`month` name a different period by
    the month it ends in, and naming a `user_id` keeps a run - or a test - from
    raising invoices against customers it never meant to touch.
    """
    _require_super(principal)
    months = int(body.get("months") or invoicing.every_months())
    closed = invoicing.billing.last_closed_period(date.today(), months)
    year = int(body.get("year") or closed[0])
    month = int(body.get("month") or closed[1])
    return await invoicing.raise_for_period(
        principal, session, year, month, months,
        user_id=int(body["user_id"]) if body.get("user_id") else None)

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

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_manager
from app.config import settings
from app.database import get_session
from app.models.billing import BillingAccount, Invoice, InvoiceLine
from app.services import auth, invoice_pdf, invoicing, modules
from app.services.auth import Principal

logger = logging.getLogger("tacho.invoices")

router = APIRouter(prefix="/api/billing", tags=["billing"])


def _require_super(principal: Principal) -> None:
    if not modules.is_super_admin(principal):
        raise HTTPException(status_code=403, detail="Only a super administrator can see invoicing.")


def _account_json(account: BillingAccount) -> dict:
    return {
        "user_id": account.user_id, "name": account.name,
        "account_email": account.account_email, "invoicing_email": account.invoicing_email,
        "send_to": account.send_to, "started_on": account.started_on.isoformat(),
        "active": account.active,
        "rates": {"tracking": _number(account.rate_tracking),
                  "camera": _number(account.rate_camera),
                  "tachograph": _number(account.rate_tachograph)},
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
        "vat_rate": settings.invoice_vat_rate,
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
    for item in ("tracking", "camera", "tachograph"):
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
    """What an account would be charged for a month. Nothing is issued or sent."""
    _require_super(principal)
    account = (await session.execute(
        select(BillingAccount).where(
            BillingAccount.user_id == int(body["user_id"])))).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="That account is not set up for billing.")

    today = date.today()
    built = await invoicing.build_for(principal, account, int(body.get("year") or today.year),
                                      int(body.get("month") or today.month), session)
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
        "lines": [{"description": line.description, "rate": float(line.rate),
                   "days": line.days, "days_in_month": line.days_in_month,
                   "amount": float(line.amount)} for line in lines],
    }


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
async def run_month(body: dict = Body(default={}),
                    principal: Principal = Depends(require_manager),
                    session: AsyncSession = Depends(get_session)):
    """Raise this month's invoices as drafts. Sending is a separate step."""
    _require_super(principal)
    today = date.today()
    year = int(body.get("year") or today.year)
    month = int(body.get("month") or today.month)

    # A run covers every active account unless one is named. Naming one keeps a
    # run - or a test - from raising invoices against customers it never meant
    # to touch.
    query = select(BillingAccount).where(BillingAccount.active.is_(True))
    if body.get("user_id"):
        query = query.where(BillingAccount.user_id == int(body["user_id"]))
    accounts = (await session.execute(query)).scalars().all()
    last = (await session.execute(
        select(Invoice.number).where(Invoice.number.like(f"{settings.invoice_number_prefix}-{year}-%"))
        .order_by(Invoice.number.desc()).limit(1))).scalars().first()

    # Any invoice overlapping this month means the account is already billed for
    # it. Comparing against the 1st alone would miss a first invoice that starts
    # mid-month, and the customer would be billed twice.
    month_start, month_end = invoicing.billing.month_range(year, month)

    raised, skipped = [], []
    for account in accounts:
        existing = (await session.execute(
            select(Invoice).where(Invoice.user_id == account.user_id,
                                  Invoice.period_start <= month_end,
                                  Invoice.period_end >= month_start))).scalars().first()
        if existing:
            skipped.append({"account": account.name, "why": f"already invoiced as {existing.number}"})
            continue

        built = await invoicing.build_for(principal, account, year, month, session)
        if not built.lines:
            skipped.append({"account": account.name, "why": "nothing chargeable this period"})
            continue

        last = invoicing.next_number(year, last)
        invoice = Invoice(
            number=last, user_id=account.user_id, account_name=account.name,
            period_start=built.period_start, period_end=built.period_end,
            issued_on=today, net=built.net, vat=built.vat, total=built.total,
            vat_rate=Decimal(str(settings.invoice_vat_rate)), status="draft",
            sent_to=account.send_to)
        for position, line in enumerate(built.lines):
            invoice.lines.append(InvoiceLine(
                position=position, vehicle=line.vehicle, item=line.item,
                description=line.describe(), rate=line.rate, days=line.days,
                days_in_month=line.days_in_month, amount=line.amount))
        session.add(invoice)
        raised.append({"account": account.name, "number": invoice.number,
                       "total": float(built.total)})

    await session.commit()
    return {"raised": raised, "skipped": skipped, "not_ready": invoicing.not_ready()}

"""Turning a customer's actual fleet into an invoice.

`billing.py` does the sums; this decides what goes into them - which vehicles
are on an account, what is fitted to each, and since when.

What counts as fitted:
  tracking    every vehicle on the account. It is on the platform, so it is
              being tracked.
  camera      the vehicle carries a cmsv9DeviceId, meaning a DVR is paired to
              it and its video is being relayed.
  tachograph  the compliance side holds a vehicle of that registration with a
              tachograph serial against it, so its cards and unit downloads
              are being processed.

Since when: Traccar keeps no record of the day a vehicle was added, so one is
kept as a `billingSince` attribute on the device. Where that is missing - every
vehicle fitted before this module existed - the account's own start date is
used, which bills them from the day the customer joined and never earlier.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.billing import BillingAccount, Invoice, InvoiceLine
from app.models.core import Vehicle
from app.models.mail import EmailSend
from app.services import auth, billing, invoice_pdf, mailer

logger = logging.getLogger("tacho.invoices")

BILLING_SINCE = "billingSince"


def standard_rates() -> dict[str, Decimal]:
    """What a vehicle costs per month on each package, before any account
    has agreed something different."""
    return {"live": Decimal(str(settings.rate_live)),
            "tacho": Decimal(str(settings.rate_tacho))}


def rates_for(account: BillingAccount) -> dict[str, Decimal]:
    """An account's own rates where it has them, the standard ones otherwise."""
    standard = standard_rates()
    agreed = {"live": account.rate_live, "tacho": account.rate_tacho}
    return {item: Decimal(agreed[item]) if agreed[item] is not None else standard[item]
            for item in standard}


def not_ready() -> list[str]:
    """What is still missing before an invoice may be sent to a customer.

    Placeholders are fine for building and previewing; they must never reach a
    customer, so this is checked before anything is emailed.
    """
    missing = []
    if not any((settings.rate_live, settings.rate_tacho)):
        missing.append("the monthly rates are all zero")
    # Checked by shape rather than by looking for "0000", which a real VAT
    # number is perfectly entitled to contain.
    if invoice_pdf.placeholder(settings.company_vat_number):
        missing.append("the VAT number is a placeholder")
    if not settings.smtp_host:
        missing.append("no mail server is set up, so nothing can be emailed")
    return missing


def _since(device: dict, account: BillingAccount) -> date:
    """The day this vehicle started costing the customer money."""
    stamped = (device.get("attributes") or {}).get(BILLING_SINCE)
    if stamped:
        try:
            return datetime.fromisoformat(str(stamped)[:10]).date()
        except ValueError:
            logger.warning("device %s has an unreadable %s: %r",
                           device.get("name"), BILLING_SINCE, stamped)
    return account.started_on


async def _tacho_registrations(session: AsyncSession) -> set[str]:
    """Registrations the compliance side is doing tachograph work for."""
    rows = (await session.execute(
        select(Vehicle.registration).where(Vehicle.tachograph_serial.isnot(None)))).scalars().all()
    return {str(r).replace(" ", "").upper() for r in rows if r}


async def fleet_for(principal, account: BillingAccount, session: AsyncSession) -> list[dict]:
    """Every chargeable vehicle on an account, with what is fitted to it."""
    devices = await auth.traccar_get(principal, f"/api/devices?userId={account.user_id}") or []
    tacho = await _tacho_registrations(session)

    fleet = []
    for device in devices:
        attributes = device.get("attributes") or {}
        name = (device.get("name") or "").strip() or f"Device {device.get('id')}"
        fitted = ["tracking"]
        if attributes.get("cmsv9DeviceId"):
            fitted.append("camera")
        if name.replace(" ", "").upper() in tacho:
            fitted.append("tachograph")
        fleet.append({"name": name, "since": _since(device, account), "fitted": fitted,
                      "device_id": device.get("id")})
    return fleet


def every_months() -> int:
    """How many months one invoice covers. Three by default: customers are
    billed quarterly, on the first morning of the new quarter."""
    return max(1, int(settings.invoice_every_months or 1))


async def build_for(principal, account: BillingAccount, year: int, month: int,
                    session: AsyncSession, months: int | None = None) -> billing.Invoice:
    """What this account owes for a period ending in the given month.

    `months` is how long that period is; it defaults to the configured billing
    cycle, so one invoice covers a quarter unless asked otherwise.
    """
    fleet = await fleet_for(principal, account, session)
    return billing.build_period(
        account=account.name, vehicles=fleet, rates=rates_for(account),
        year=year, month=month, months=every_months() if months is None else months,
        account_since=account.started_on,
        vat_rate=Decimal(str(settings.invoice_vat_rate)))


async def refresh_contacts(principal, session: AsyncSession, accounts) -> list[dict]:
    """Bring each account's name and signup email back in line with DH FleetView.

    The signup email is kept as a copy here rather than read from DH FleetView
    every time, so that an invoice records where it was actually sent. But a
    copy goes stale: a customer who changes the address they sign in with would
    otherwise keep receiving invoices at the old one until somebody happened to
    open and save their billing account. So it is refreshed at the start of
    every run, which is the last moment before it matters.

    If DH FleetView cannot be reached, nothing is changed - a stale address is
    far better than a blank one.
    """
    users = await auth.traccar_get(principal, "/api/users")
    if not users:
        logger.warning("could not refresh the billing contacts from DH FleetView")
        return []

    by_id = {u["id"]: u for u in users if isinstance(u, dict) and u.get("id")}
    changed = []
    for account in accounts:
        user = by_id.get(account.user_id)
        if not user:
            continue
        email = (user.get("email") or "").strip()
        if email and email != account.account_email:
            changed.append({"account": account.name, "user_id": account.user_id,
                            "was": account.account_email, "now": email})
            logger.info("%s signs in as %s now, not %s; invoicing updated",
                        account.name, email, account.account_email)
            account.account_email = email
        name = (user.get("name") or "").strip()
        if name and name != account.name:
            account.name = name
    if changed:
        await session.commit()
    return changed


async def raise_for_period(principal, session: AsyncSession, year: int, month: int,
                           months: int | None = None, user_id: int | None = None,
                           today: date | None = None) -> dict:
    """Raise the invoices for one billing period, as drafts. Nothing is sent.

    Shared by the button and by the scheduled run so that an invoice raised at
    six on a Monday morning is identical to one raised by hand. An account
    already holding an invoice that overlaps the period is left alone: billing
    a customer twice for the same month is the one mistake here that cannot be
    quietly corrected.
    """
    months = every_months() if months is None else months
    today = today or date.today()

    query = select(BillingAccount).where(BillingAccount.active.is_(True))
    if user_id:
        query = query.where(BillingAccount.user_id == int(user_id))
    accounts = (await session.execute(query)).scalars().all()
    # Done before anything is priced, so an invoice carries the address the
    # customer signs in with today rather than the one they used to.
    moved = await refresh_contacts(principal, session, accounts)
    last = (await session.execute(
        select(Invoice.number)
        .where(Invoice.number.like(f"{settings.invoice_number_prefix}-{year}-%"))
        .order_by(Invoice.number.desc()).limit(1))).scalars().first()

    period_start, period_end = billing.period_range(year, month, months)

    raised, skipped = [], []
    for account in accounts:
        existing = (await session.execute(
            select(Invoice).where(Invoice.user_id == account.user_id,
                                  Invoice.period_start <= period_end,
                                  Invoice.period_end >= period_start))).scalars().first()
        if existing:
            skipped.append({"account": account.name, "user_id": account.user_id,
                            "why": f"already invoiced as {existing.number}"})
            continue

        built = await build_for(principal, account, year, month, session, months)
        if not built.lines:
            skipped.append({"account": account.name, "user_id": account.user_id,
                            "why": "nothing chargeable this period"})
            continue

        last = next_number(year, last)
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
        raised.append({"account": account.name, "user_id": account.user_id,
                       "number": invoice.number, "total": float(built.total),
                       "id": None})

    await session.commit()
    return {"raised": raised, "skipped": skipped, "not_ready": not_ready(),
            "contacts_updated": moved,
            "period": {"start": period_start.isoformat(), "end": period_end.isoformat(),
                       "key": billing.period_key(year, month, months)}}


def email_body(invoice: Invoice) -> str:
    """What the customer reads. The invoice itself is attached."""
    period = invoice_pdf.invoice_period(invoice)
    return (
        f"Dear {invoice.account_name},\n\n"
        f"Please find attached invoice {invoice.number} for {period}, "
        f"for {invoice_pdf.money(invoice.total)} including VAT.\n\n"
        f"{settings.invoice_payment_terms}\n\n"
        f"If anything on it needs explaining, reply to this email and we will go "
        f"through it with you.\n\n"
        f"{settings.company_name}\n"
    )


async def render_invoice(session: AsyncSession, invoice: Invoice,
                         customer_email: str | None = None) -> bytes:
    lines = (await session.execute(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)
        .order_by(InvoiceLine.position))).scalars().all()
    return invoice_pdf.render(invoice, lines, customer_name=invoice.account_name,
                              customer_email=customer_email)


async def email_invoice(session: AsyncSession, invoice: Invoice, to: str | None = None,
                        *, automatic: bool = False) -> str:
    """Email one invoice with its PDF attached, and record that it went.

    Raises mailer.MailError if it did not, having recorded that too - an
    invoice that failed to send has to be visible, or it is simply lost.
    """
    address = (to or invoice.sent_to or "").strip()
    if not address:
        account = (await session.execute(
            select(BillingAccount).where(
                BillingAccount.user_id == invoice.user_id))).scalar_one_or_none()
        address = (account.send_to if account else "") or ""
    if not mailer.valid(address):
        raise mailer.MailError(
            f"{address or 'No address'} is not an email address. Set an invoicing "
            "email on the account, or give one here.")

    pdf = await render_invoice(session, invoice, address)
    subject = f"Invoice {invoice.number} from {settings.company_name}"
    period = billing_period_key(invoice)

    try:
        await mailer.send(address, subject, email_body(invoice),
                          [(f"{invoice.number}.pdf", pdf, "pdf")])
    except mailer.MailError as exc:
        invoice.status, invoice.detail = "failed", str(exc)[:500]
        session.add(EmailSend(kind="invoice", period_key=period,
                              reference=invoice.number, user_id=invoice.user_id,
                              account_name=invoice.account_name, recipient=address,
                              subject=subject, status="failed", detail=str(exc)[:1000],
                              automatic=automatic))
        await session.commit()
        raise

    invoice.status, invoice.sent_to = "sent", address
    invoice.sent_at = datetime.now(timezone.utc)
    invoice.detail = None
    session.add(EmailSend(kind="invoice", period_key=period, reference=invoice.number,
                          user_id=invoice.user_id, account_name=invoice.account_name,
                          recipient=address, subject=subject, status="sent",
                          automatic=automatic))
    await session.commit()
    logger.info("emailed %s to %s", invoice.number, address)
    return address


def billing_period_key(invoice: Invoice) -> str:
    """The period an invoice belongs to, named as the scheduler names it."""
    end = invoice.period_end
    months = every_months()
    return billing.period_key(end.year, end.month, months)


def next_number(year: int, last: str | None) -> str:
    """Invoice numbers run in order within a year: DH-2026-0001, then 0002.

    Gaps and reuse both cause questions from an accountant, so the number comes
    from the last one issued rather than from a count of rows.
    """
    prefix = f"{settings.invoice_number_prefix}-{year}-"
    if last and last.startswith(prefix):
        try:
            return f"{prefix}{int(last[len(prefix):]) + 1:04d}"
        except ValueError:
            logger.warning("could not read the last invoice number %r", last)
    return f"{prefix}0001"

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
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.billing import BillingAccount
from app.models.core import Vehicle
from app.services import auth, billing

logger = logging.getLogger("tacho.invoices")

BILLING_SINCE = "billingSince"


def standard_rates() -> dict[str, Decimal]:
    return {"tracking": Decimal(str(settings.rate_tracking)),
            "camera": Decimal(str(settings.rate_camera)),
            "tachograph": Decimal(str(settings.rate_tachograph))}


def rates_for(account: BillingAccount) -> dict[str, Decimal]:
    """An account's own rates where it has them, the standard ones otherwise."""
    standard = standard_rates()
    agreed = {"tracking": account.rate_tracking, "camera": account.rate_camera,
              "tachograph": account.rate_tachograph}
    return {item: Decimal(agreed[item]) if agreed[item] is not None else standard[item]
            for item in standard}


def not_ready() -> list[str]:
    """What is still missing before an invoice may be sent to a customer.

    Placeholders are fine for building and previewing; they must never reach a
    customer, so this is checked before anything is emailed.
    """
    missing = []
    if not any((settings.rate_tracking, settings.rate_camera, settings.rate_tachograph)):
        missing.append("the monthly rates are all zero")
    if not settings.company_vat_number or "0000" in settings.company_vat_number:
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


async def build_for(principal, account: BillingAccount, year: int, month: int,
                    session: AsyncSession) -> billing.Invoice:
    """What this account owes for one month, from its fleet as it stands."""
    fleet = await fleet_for(principal, account, session)
    return billing.build_invoice(
        account=account.name, vehicles=fleet, rates=rates_for(account),
        year=year, month=month, account_since=account.started_on,
        vat_rate=Decimal(str(settings.invoice_vat_rate)))


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

"""Download-window compliance: are driver cards being downloaded within 28 days
and vehicle units within 90 days? This is the operational core an O-licence /
Earned Recognition review checks — proof each card/VU is downloaded on time.

Status per entity is derived from the most recent archived TachoFile for that
driver_ref / vehicle_ref, against the configured windows.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.core import Device, Driver
from app.models.tacho import TachoFile


def _status(days: float | None, interval: int, warning: int) -> str:
    if days is None:
        return "no_data"
    if days > interval:
        return "overdue"
    if days >= warning:
        return "due_soon"
    return "compliant"


async def _latest_by(session: AsyncSession, column, kind: str) -> dict[str, datetime]:
    rows = (await session.execute(
        select(column, func.max(TachoFile.created_at))
        .where(TachoFile.file_kind == kind, column.isnot(None))
        .group_by(column)
    )).all()
    return {ref: ts for ref, ts in rows if ref}


async def compliance(session: AsyncSession, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)

    driver_files = await _latest_by(session, TachoFile.driver_ref, "driver_card")
    vehicle_files = await _latest_by(session, TachoFile.vehicle_ref, "vehicle_unit")

    # Known entities (so ones never downloaded still show as no_data/overdue).
    known_drivers: dict[str, str] = {}
    alias: dict[str, str] = {}      # any identifier the driver goes by -> canonical
    for d in (await session.execute(select(Driver))).scalars().all():
        canonical = d.card_number or d.name
        if not canonical:
            continue
        known_drivers[canonical] = d.name or d.card_number
        for known_as in (d.card_number, d.name):
            if known_as:
                alias[known_as] = canonical
    # A card file is filed under the holder's name, a driver record is usually
    # keyed by card number. Fold one onto the other so the same person is one
    # row and not two.
    if alias:
        folded: dict[str, datetime] = {}
        for ref, ts in driver_files.items():
            key = alias.get(ref, ref)
            if key not in folded or ts > folded[key]:
                folded[key] = ts
        driver_files = folded
    known_vehicles = {
        d.vehicle_reg: d.vehicle_reg
        for d in (await session.execute(select(Device))).scalars().all() if d.vehicle_reg
    }

    def rows(latest: dict, known: dict, interval: int, warning: int, kind: str) -> list[dict]:
        refs = set(latest) | set(known)
        out = []
        for ref in sorted(refs):
            ts = latest.get(ref)
            days = (now - ts).total_seconds() / 86400 if ts else None
            out.append({
                "kind": kind,
                "ref": ref,
                "label": known.get(ref, ref),
                "last_download": ts.isoformat() if ts else None,
                "days_since": round(days, 1) if days is not None else None,
                "interval_days": interval,
                "status": _status(days, interval, warning),
            })
        # worst first
        order = {"overdue": 0, "no_data": 1, "due_soon": 2, "compliant": 3}
        out.sort(key=lambda r: (order.get(r["status"], 9), -(r["days_since"] or 0)))
        return out

    drivers = rows(driver_files, known_drivers,
                   settings.driver_interval_days, settings.driver_warning_days, "driver")
    vehicles = rows(vehicle_files, known_vehicles,
                    settings.vehicle_interval_days, settings.vehicle_warning_days, "vehicle")

    def tally(rs):
        t = {"compliant": 0, "due_soon": 0, "overdue": 0, "no_data": 0}
        for r in rs:
            t[r["status"]] = t.get(r["status"], 0) + 1
        return t

    return {
        "generated_at": now.isoformat(),
        "windows": {"driver_days": settings.driver_interval_days, "vehicle_days": settings.vehicle_interval_days},
        "drivers": drivers,
        "vehicles": vehicles,
        "summary": {"drivers": tally(drivers), "vehicles": tally(vehicles)},
    }

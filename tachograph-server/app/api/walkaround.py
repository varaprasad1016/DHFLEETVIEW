"""Daily walkaround check + defect reporting API. Every route is gated by the
monthly licence via `require_license`, so it locks with the rest of the
compliance suite.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_license
from app.database import get_session
from app.models.walkaround import WalkaroundCheck, WalkaroundDefect

router = APIRouter(prefix="/api/walkaround", tags=["walkaround"], dependencies=[Depends(require_license)])


# --- DVSA "Guide to maintaining roadworthiness" first-use walkaround items ---
CHECK_ITEMS = {
    "hgv": [
        "Fuel/oil leaks", "Battery security & condition", "Diesel exhaust fluid (AdBlue)",
        "Windscreen, wipers & washers", "Mirrors & indirect vision devices", "Glass & view of road",
        "Dashboard warning lights", "Steering", "Horn", "Brakes & air build-up",
        "Height marker", "Seat belts & cab interior", "Lights, indicators & markers",
        "Reflectors & markings", "Tyres & wheel fixings", "Spray suppression",
        "Load security", "Number plate", "Bodywork & wings", "Trailer coupling & security",
        "Trailer landing legs", "Electrical connections",
    ],
    "psv": [
        "Fuel/oil leaks", "Battery security & condition", "Windscreen, wipers & washers",
        "Mirrors", "Dashboard warning lights", "Steering", "Horn", "Brakes & air build-up",
        "Seat belts", "Passenger doors & exits", "Lights & indicators", "Reflectors",
        "Tyres & wheel fixings", "Number plate", "Bodywork", "Wheelchair ramp/lift",
        "Emergency equipment", "Destination display",
    ],
    "van": [
        "Fuel/oil leaks", "Windscreen, wipers & washers", "Mirrors", "Dashboard warning lights",
        "Steering", "Horn", "Brakes", "Seat belts", "Lights & indicators",
        "Tyres & wheel fixings", "Number plate", "Bodywork", "Load security",
    ],
    "car": [
        "Windscreen, wipers & washers", "Mirrors", "Dashboard warning lights", "Steering",
        "Horn", "Brakes", "Seat belts", "Lights & indicators", "Tyres", "Number plate",
    ],
}


class DefectIn(BaseModel):
    item: str
    severity: str = Field(default="major", pattern="^(dangerous|major|minor)$")
    description: str | None = None
    photo_key: str | None = None


class CheckIn(BaseModel):
    vehicle_reg: str
    driver_name: str | None = None
    check_type: str = Field(default="hgv", pattern="^(hgv|psv|van|car)$")
    odometer_km: int | None = None
    location: str | None = None
    notes: str | None = None
    safe_to_drive: bool = True
    defects: list[DefectIn] = []


class RectifyIn(BaseModel):
    rectified_by: str | None = None
    rectification_notes: str | None = None
    status: str = Field(default="rectified", pattern="^(rectified|monitoring|open)$")


@router.get("/items")
async def items(check_type: str = "hgv") -> dict:
    return {"check_type": check_type, "items": CHECK_ITEMS.get(check_type, CHECK_ITEMS["hgv"])}


@router.post("/checks", status_code=201)
async def submit_check(body: CheckIn, session: AsyncSession = Depends(get_session)) -> dict:
    reg = body.vehicle_reg.strip().upper().replace(" ", "")
    if not reg:
        raise HTTPException(status_code=400, detail="vehicle_reg is required.")

    check = WalkaroundCheck(
        vehicle_reg=reg,
        driver_name=body.driver_name,
        check_type=body.check_type,
        odometer_km=body.odometer_km,
        location=body.location,
        notes=body.notes,
        safe_to_drive=body.safe_to_drive,
        result="defects" if body.defects else "pass",
    )
    session.add(check)
    await session.flush()  # get check.id

    for d in body.defects:
        session.add(WalkaroundDefect(
            check_id=check.id,
            vehicle_reg=reg,
            item=d.item,
            severity=d.severity,
            description=d.description,
            photo_key=d.photo_key,
            reported_by=body.driver_name,
        ))
    await session.commit()

    has_blocking = any(d.severity in ("dangerous", "major") for d in body.defects)
    return {
        "id": str(check.id),
        "vehicle_reg": reg,
        "result": check.result,
        "defect_count": len(body.defects),
        "advice": (
            "Dangerous/major defect reported — vehicle should not be used until rectified."
            if has_blocking else "No blocking defects recorded."
        ),
    }


@router.get("/checks")
async def list_checks(limit: int = 50, session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.execute(
        select(WalkaroundCheck).order_by(WalkaroundCheck.created_at.desc()).limit(min(limit, 200))
    )).scalars().all()
    # defect counts per check
    counts = dict((await session.execute(
        select(WalkaroundDefect.check_id, func.count()).group_by(WalkaroundDefect.check_id)
    )).all())
    return [{
        "id": str(c.id),
        "vehicle_reg": c.vehicle_reg,
        "driver_name": c.driver_name,
        "check_type": c.check_type,
        "odometer_km": c.odometer_km,
        "result": c.result,
        "safe_to_drive": c.safe_to_drive,
        "defect_count": counts.get(c.id, 0),
        "created_at": c.created_at.isoformat() if c.created_at else None,
    } for c in rows]


@router.get("/defects")
async def list_defects(status: str = "open", session: AsyncSession = Depends(get_session)) -> list[dict]:
    stmt = select(WalkaroundDefect).order_by(WalkaroundDefect.created_at.desc())
    if status != "all":
        stmt = stmt.where(WalkaroundDefect.status == status)
    rows = (await session.execute(stmt.limit(500))).scalars().all()
    return [{
        "id": str(d.id),
        "vehicle_reg": d.vehicle_reg,
        "item": d.item,
        "severity": d.severity,
        "description": d.description,
        "status": d.status,
        "reported_by": d.reported_by,
        "rectified_by": d.rectified_by,
        "rectification_notes": d.rectification_notes,
        "rectified_at": d.rectified_at.isoformat() if d.rectified_at else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    } for d in rows]


@router.post("/defects/{defect_id}/rectify")
async def rectify_defect(
    defect_id: uuid.UUID, body: RectifyIn, session: AsyncSession = Depends(get_session)) -> dict:
    defect = (await session.execute(
        select(WalkaroundDefect).where(WalkaroundDefect.id == defect_id)
    )).scalar_one_or_none()
    if defect is None:
        raise HTTPException(status_code=404, detail="Defect not found.")
    defect.status = body.status
    defect.rectified_by = body.rectified_by
    defect.rectification_notes = body.rectification_notes
    defect.rectified_at = datetime.now(timezone.utc) if body.status == "rectified" else None
    await session.commit()
    return {"id": str(defect.id), "status": defect.status}


@router.get("/summary")
async def summary(session: AsyncSession = Depends(get_session)) -> dict:
    open_defects = (await session.execute(
        select(func.count()).select_from(WalkaroundDefect).where(WalkaroundDefect.status == "open")
    )).scalar_one()
    dangerous = (await session.execute(
        select(func.count()).select_from(WalkaroundDefect).where(
            WalkaroundDefect.status == "open", WalkaroundDefect.severity == "dangerous")
    )).scalar_one()
    checks_total = (await session.execute(
        select(func.count()).select_from(WalkaroundCheck)
    )).scalar_one()
    return {"checks_total": checks_total, "open_defects": open_defects, "open_dangerous": dangerous}

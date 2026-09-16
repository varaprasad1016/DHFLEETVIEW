"""Daily walkaround check + defect reporting API. Every route is gated by the
monthly licence via `require_license`, so it locks with the rest of the
compliance suite.

Supports optional per-item photos and a driver signature captured on the form,
plus a date-filtered history so past walkaround reports can be pulled back.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_license, require_manager, require_module
from app.database import get_session
from app.models.walkaround import WalkaroundCheck, WalkaroundDefect, WalkaroundPhoto
from app.services import media_store

router = APIRouter(prefix="/api/walkaround", tags=["walkaround"], dependencies=[Depends(require_license)])
MANAGER = [Depends(require_manager)]
REPORTS = MANAGER + [Depends(require_module("walkaround_reports"))]
DEFECTS = MANAGER + [Depends(require_module("defects"))]


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
    photo: str | None = None   # optional base64 data URL


class PhotoIn(BaseModel):
    item: str | None = None    # which check item (null = general)
    image: str                 # base64 data URL


class CheckIn(BaseModel):
    vehicle_reg: str
    driver_name: str | None = None
    check_type: str = Field(default="hgv", pattern="^(hgv|psv|van|car)$")
    odometer_km: int | None = None
    location: str | None = None
    notes: str | None = None
    safe_to_drive: bool = True
    defects: list[DefectIn] = []
    photos: list[PhotoIn] = []          # optional per-item / general photos
    signature: str | None = None        # optional base64 data URL of the signature
    phase: str = Field(default="pre_use", pattern="^(pre_use|end_of_day|fault_report)$")
    fuel_level: str | None = Field(default=None, pattern="^(empty|1/4|1/2|3/4|full)$")
    adblue_level: str | None = Field(default=None, pattern="^(empty|1/4|1/2|3/4|full)$")
    duration_seconds: int | None = None
    shift_id: uuid.UUID | None = None


class RectifyIn(BaseModel):
    rectified_by: str | None = None
    rectification_notes: str | None = None
    status: str = Field(default="rectified", pattern="^(rectified|monitoring|open)$")


def _parse_day(value: str, end: bool = False) -> datetime:
    """Parse a YYYY-MM-DD (or ISO) string to a UTC datetime; end -> next midnight."""
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        d = datetime.combine(datetime.strptime(value[:10], "%Y-%m-%d").date(), time.min)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    if end and len(value) <= 10:
        d = d + timedelta(days=1)
    return d


def _store(data_url: str) -> dict:
    try:
        return media_store.save_data_url(data_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad image: {e}")


@router.get("/items", dependencies=REPORTS)
async def items(check_type: str = "hgv") -> dict:
    return {"check_type": check_type, "items": CHECK_ITEMS.get(check_type, CHECK_ITEMS["hgv"])}


@router.post("/checks", status_code=201, dependencies=REPORTS)
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
        phase=body.phase,
        fuel_level=body.fuel_level,
        adblue_level=body.adblue_level,
        duration_seconds=body.duration_seconds,
        shift_id=body.shift_id,
    )
    if body.signature:
        check.signature_path = _store(body.signature)["storage_path"]
    session.add(check)
    await session.flush()  # get check.id

    for d in body.defects:
        session.add(WalkaroundDefect(
            check_id=check.id, vehicle_reg=reg, item=d.item, severity=d.severity,
            description=d.description, reported_by=body.driver_name))
        if d.photo:
            meta = _store(d.photo)
            session.add(WalkaroundPhoto(
                check_id=check.id, item=d.item,
                content_type=meta["content_type"], storage_path=meta["storage_path"]))

    for p in body.photos:
        meta = _store(p.image)
        session.add(WalkaroundPhoto(
            check_id=check.id, item=p.item,
            content_type=meta["content_type"], storage_path=meta["storage_path"]))

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


@router.get("/checks", dependencies=REPORTS)
async def list_checks(limit: int = 100, start: str | None = None, end: str | None = None,
                      reg: str | None = None, driver: str | None = None, phase: str | None = None,
                      session: AsyncSession = Depends(get_session)) -> list[dict]:
    stmt = select(WalkaroundCheck).order_by(WalkaroundCheck.created_at.desc())
    if reg:
        stmt = stmt.where(WalkaroundCheck.vehicle_reg == reg.strip().upper().replace(" ", ""))
    if driver:
        stmt = stmt.where(WalkaroundCheck.driver_name.ilike(f"%{driver}%"))
    if phase:
        stmt = stmt.where(WalkaroundCheck.phase == phase)
    if start:
        stmt = stmt.where(WalkaroundCheck.created_at >= _parse_day(start))
    if end:
        stmt = stmt.where(WalkaroundCheck.created_at < _parse_day(end, end=True))
    rows = (await session.execute(stmt.limit(min(limit, 500)))).scalars().all()

    counts = dict((await session.execute(
        select(WalkaroundDefect.check_id, func.count()).group_by(WalkaroundDefect.check_id)
    )).all())
    photo_counts = dict((await session.execute(
        select(WalkaroundPhoto.check_id, func.count()).group_by(WalkaroundPhoto.check_id)
    )).all())
    return [{
        "id": str(c.id),
        "vehicle_reg": c.vehicle_reg,
        "driver_name": c.driver_name,
        "check_type": c.check_type,
        "phase": c.phase,
        "fuel_level": c.fuel_level,
        "adblue_level": c.adblue_level,
        "duration_seconds": c.duration_seconds,
        "odometer_km": c.odometer_km,
        "result": c.result,
        "safe_to_drive": c.safe_to_drive,
        "defect_count": counts.get(c.id, 0),
        "photo_count": photo_counts.get(c.id, 0),
        "has_signature": bool(c.signature_path),
        "created_at": c.created_at.isoformat() if c.created_at else None,
    } for c in rows]


@router.get("/checks/{check_id}", dependencies=REPORTS)
async def get_check(check_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    c = (await session.execute(
        select(WalkaroundCheck).where(WalkaroundCheck.id == check_id))).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="Check not found.")
    defects = (await session.execute(
        select(WalkaroundDefect).where(WalkaroundDefect.check_id == check_id))).scalars().all()
    photos = (await session.execute(
        select(WalkaroundPhoto).where(WalkaroundPhoto.check_id == check_id))).scalars().all()
    return {
        "id": str(c.id), "vehicle_reg": c.vehicle_reg, "driver_name": c.driver_name,
        "check_type": c.check_type, "odometer_km": c.odometer_km, "location": c.location,
        "phase": c.phase, "fuel_level": c.fuel_level, "adblue_level": c.adblue_level,
        "duration_seconds": c.duration_seconds,
        "result": c.result, "safe_to_drive": c.safe_to_drive, "notes": c.notes,
        "has_signature": bool(c.signature_path),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "defects": [{
            "id": str(d.id), "item": d.item, "severity": d.severity,
            "description": d.description, "status": d.status,
        } for d in defects],
        "photos": [{"id": str(p.id), "item": p.item} for p in photos],
    }


@router.get("/photos/{photo_id}", dependencies=REPORTS)
async def get_photo(photo_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Response:
    p = (await session.execute(
        select(WalkaroundPhoto).where(WalkaroundPhoto.id == photo_id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="Photo not found.")
    try:
        return Response(content=media_store.read(p.storage_path), media_type=p.content_type)
    except OSError:
        raise HTTPException(status_code=404, detail="Photo file missing.")


@router.get("/checks/{check_id}/signature", dependencies=REPORTS)
async def get_signature(check_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Response:
    c = (await session.execute(
        select(WalkaroundCheck).where(WalkaroundCheck.id == check_id))).scalar_one_or_none()
    if c is None or not c.signature_path:
        raise HTTPException(status_code=404, detail="No signature.")
    ct = "image/png" if c.signature_path.lower().endswith("png") else "image/jpeg"
    try:
        return Response(content=media_store.read(c.signature_path), media_type=ct)
    except OSError:
        raise HTTPException(status_code=404, detail="Signature file missing.")


@router.get("/defects", dependencies=DEFECTS)
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


@router.post("/defects/{defect_id}/rectify", dependencies=DEFECTS)
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


@router.get("/summary", dependencies=DEFECTS)
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

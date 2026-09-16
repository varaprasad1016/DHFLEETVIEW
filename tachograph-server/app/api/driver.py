"""Driver mobile app API (the "Live" screen at /tacho/driver).

Composes the existing shift, job and walkaround records into what a driver
sees on one screen — the vehicle they're on, whether today's pre-use and
end-of-day checks are done, open faults and their jobs — and adds the driver
actions that had no home yet: fuel fill-ups, ad-hoc fault reports and paperwork
uploads. Licence-gated like the rest of the compliance suite.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import shifts as shifts_api
from app.api import walkaround as walkaround_api
from app.api.deps import ensure_own, require_driver, require_license, require_module
from app.config import settings
from app.database import get_session
from app.models.core import Company, Device, Vehicle
from app.models.driver_app import DriverPaperwork, FuelLog
from app.models.shifts import Job, Shift
from app.models.vehicle import VehicleStatus
from app.models.walkaround import WalkaroundCheck, WalkaroundDefect, WalkaroundPhoto
from app.services import media_store
from app.services.auth import Principal

router = APIRouter(prefix="/api/driver", tags=["driver"],
                   dependencies=[Depends(require_license), Depends(require_driver), Depends(require_module("driver_app"))])

LONDON = ZoneInfo("Europe/London")
ACTIVE_SHIFT = ("clocked_in", "on_break", "active")
OPEN_JOB = ("pending", "accepted", "in_progress")
LEVEL_PCT = {"empty": 0, "1/4": 25, "1/2": 50, "3/4": 75, "full": 100}
_MAX_UPLOAD = 10 * 1024 * 1024


def norm_reg(reg: str | None) -> str:
    return (reg or "").strip().upper().replace(" ", "")


# --- walkaround wizard template ------------------------------------------------
# Item names match walkaround.CHECK_ITEMS so defects stay comparable with the
# existing reports; `hint` is the DVSA guidance shown behind the (i) button.

_HGV_IN_CAB = [
    ("Mirrors & indirect vision devices", "All mirrors and cameras present, secure, not cracked, and give a clear view."),
    ("Glass & view of road", "No damage or obstructions in the driver's view; nothing stuck to the glass in the swept area."),
    ("Windscreen, wipers & washers", "Wipers work and are not worn; washers spray and have fluid."),
    ("Dashboard warning lights", "Warning lights work and none are showing a fault once the engine is running."),
    ("Steering", "No excessive play; power steering works and the wheel doesn't pull or stick."),
    ("Horn", "Horn works and is easy to reach from the driving seat."),
    ("Brakes & air build-up", "Air builds up correctly, no leaks audible, service and parking brakes hold."),
    ("Height marker", "The vehicle height shown in the cab is correct for today's load or trailer."),
    ("Seat belts & cab interior", "Belts latch, retract and aren't cut; seats secure; cab steps and doors safe."),
]
_HGV_OUTSIDE = [
    ("Fuel/oil leaks", "No fuel, oil or coolant leaking; fuel cap fits and seals."),
    ("Battery security & condition", "Battery secure, not leaking, box closed."),
    ("Diesel exhaust fluid (AdBlue)", "AdBlue topped up and cap secure; no warning on the dash."),
    ("Lights, indicators & markers", "All lamps, indicators and side markers work, are clean and the right colour."),
    ("Reflectors & markings", "Reflectors and rear/side markings are present, clean and secure."),
    ("Tyres & wheel fixings", "Tread at least 1mm, no cuts or bulges, inflated; wheel nuts and indicators in place."),
    ("Spray suppression", "Mudflaps and spray suppression fitted and secure."),
    ("Load security", "Load is secure, not overloaded, and doors/curtains are closed and fastened."),
    ("Number plate", "Plate correct, clean, secure and lit."),
    ("Bodywork & wings", "No loose panels or sharp edges; wings and guards secure."),
    ("Trailer coupling & security", "Fifth wheel/coupling locked, secure, with safety clip and no excessive play."),
    ("Trailer landing legs", "Landing legs fully raised and handle stowed."),
    ("Electrical connections", "Air and electrical lines connected, not chafing or leaking."),
]


def _template(check_type: str) -> dict:
    if check_type == "hgv":
        groups = [("in_cab", "Inside Cab", _HGV_IN_CAB), ("outside", "Outside Vehicle", _HGV_OUTSIDE)]
        steps = [{"id": gid, "title": title, "items": [{"name": n, "hint": h} for n, h in items]}
                 for gid, title, items in groups]
    else:
        names = walkaround_api.CHECK_ITEMS.get(check_type, walkaround_api.CHECK_ITEMS["hgv"])
        steps = [{"id": "checks", "title": "Vehicle Checks", "items": [{"name": n, "hint": None} for n in names]}]
    return {
        "check_type": check_type,
        "steps": [{"id": "overview", "title": "Vehicle Overview"}] + steps + [{"id": "review", "title": "Review & Sign"}],
    }


@router.get("/walkaround/template")
async def walkaround_template(check_type: str = "hgv") -> dict:
    return _template(check_type if check_type in walkaround_api.CHECK_ITEMS else "hgv")


# --- vehicle lookup ----------------------------------------------------------------

async def _vehicle_info(session: AsyncSession, reg: str) -> dict:
    v = (await session.execute(
        select(Vehicle, Company).join(Company, Company.id == Vehicle.company_id)
        .where(Vehicle.registration == reg)
    )).first()
    status = (await session.execute(select(VehicleStatus).where(VehicleStatus.reg == reg))).scalar_one_or_none()
    device = (await session.execute(select(Device).where(Device.vehicle_reg == reg))).scalars().first()
    seen_before = v is not None or status is not None or device is not None
    if not seen_before:
        seen_before = (await session.execute(
            select(Shift.id).where(Shift.vehicle_reg == reg).limit(1))).first() is not None
    company = v[1].name if v else None
    return {
        "reg": reg,
        "found": seen_before,
        "company": company,
        "make": status.make if status else None,
        "colour": status.colour if status else None,
        "fuel_type": status.fuel_type if status else None,
    }


@router.get("/vehicle")
async def lookup_vehicle(reg: str, session: AsyncSession = Depends(get_session)) -> dict:
    r = norm_reg(reg)
    if len(r) < 2:
        raise HTTPException(status_code=400, detail="Enter a registration.")
    return await _vehicle_info(session, r)


# --- the Live screen -------------------------------------------------------------------

def _london_midnight(now: datetime) -> datetime:
    local = now.astimezone(LONDON)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


async def _active_shift(session: AsyncSession, driver: str) -> Shift | None:
    return (await session.execute(
        select(Shift).where(func.lower(Shift.driver_name) == driver.lower(), Shift.status.in_(ACTIVE_SHIFT))
        .order_by(Shift.clocked_in_at.desc())
    )).scalars().first()


async def _compliance(session: AsyncSession, reg: str, shift: Shift | None) -> dict:
    """Pre-use: done once per shift. End-of-day: available once the pre-use is done,
    completed when an end-of-day check exists for this shift."""
    since = shift.clocked_in_at if shift else _london_midnight(datetime.now(timezone.utc))
    rows = (await session.execute(
        select(WalkaroundCheck).where(
            WalkaroundCheck.vehicle_reg == reg,
            WalkaroundCheck.created_at >= since,
            WalkaroundCheck.phase.in_(("pre_use", "end_of_day")),
        ).order_by(WalkaroundCheck.created_at.desc())
    )).scalars().all()
    latest = {}
    for c in rows:
        latest.setdefault(c.phase, c)

    def item(phase: str, available: bool) -> dict:
        c = latest.get(phase)
        if c:
            return {"status": "completed", "check_id": str(c.id), "result": c.result,
                    "at": c.created_at.isoformat() if c.created_at else None}
        return {"status": "available" if available else "not_available"}

    pre = item("pre_use", shift is not None)
    eod = item("end_of_day", shift is not None and pre["status"] == "completed")
    done = sum(1 for x in (pre, eod) if x["status"] == "completed")
    return {"pre_use": pre, "end_of_day": eod, "completed": done, "total": 2}


async def _open_faults(session: AsyncSession, reg: str) -> list[dict]:
    rows = (await session.execute(
        select(WalkaroundDefect).where(
            WalkaroundDefect.vehicle_reg == reg, WalkaroundDefect.status.in_(("open", "monitoring"))
        ).order_by(WalkaroundDefect.created_at.desc())
    )).scalars().all()
    return [{"id": str(d.id), "item": d.item, "severity": d.severity, "status": d.status,
             "description": d.description,
             "created_at": d.created_at.isoformat() if d.created_at else None} for d in rows]


async def _driver_jobs(session: AsyncSession, driver: str) -> list[dict]:
    today = _london_midnight(datetime.now(timezone.utc))
    rows = (await session.execute(
        select(Job).where(
            Job.driver_name.ilike(driver),
            or_(Job.status.in_(OPEN_JOB), Job.completed_at >= today),
        ).order_by(Job.scheduled_at.asc().nulls_last(), Job.assigned_at.asc())
    )).scalars().all()
    return [{**shifts_api._job_summary(j), "description": j.description,
             "pickup_location": j.pickup_location, "dropoff_location": j.dropoff_location} for j in rows]


async def _own_shift(session: AsyncSession, principal: Principal, shift_id: uuid.UUID | None) -> Shift | None:
    if shift_id is None:
        return None
    shift = (await session.execute(select(Shift).where(Shift.id == shift_id))).scalar_one_or_none()
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found.")
    ensure_own(principal, shift.driver_name)
    return shift


@router.get("/state")
async def driver_state(principal: Principal = Depends(require_driver),
                       session: AsyncSession = Depends(get_session)) -> dict:
    name = principal.name
    shift = await _active_shift(session, name)
    from app.services import modules as modules_service
    flags = await modules_service.get_flags(session)
    vehicle = None
    if shift and shift.vehicle_reg:
        reg = norm_reg(shift.vehicle_reg)
        vehicle = {
            **(await _vehicle_info(session, reg)),
            "compliance": await _compliance(session, reg, shift),
            "faults": await _open_faults(session, reg),
        }
    return {
        "driver": name,
        "shift": shifts_api._shift_summary(shift) if shift else None,
        "vehicle": vehicle,
        "jobs": await _driver_jobs(session, name) if flags["jobs"] else [],
        "modules": {"jobs": flags["jobs"]},
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


# --- shift start / end -------------------------------------------------------------------

class StartShiftIn(BaseModel):
    driver_name: str | None = None  # ignored: the signed-in driver is used
    vehicle_reg: str = Field(..., min_length=2, max_length=20)


class EndShiftIn(BaseModel):
    odometer_km: int | None = None
    fuel_level: str | None = Field(default=None, pattern="^(empty|1/4|1/2|3/4|full)$")
    adblue_level: str | None = Field(default=None, pattern="^(empty|1/4|1/2|3/4|full)$")
    notes: str | None = None


@router.post("/shift/start", status_code=201)
async def start_shift(body: StartShiftIn, principal: Principal = Depends(require_driver),
                      session: AsyncSession = Depends(get_session)) -> dict:
    return await shifts_api.clock_in(
        shifts_api.ClockInRequest(driver_name=principal.name, vehicle_reg=norm_reg(body.vehicle_reg)),
        session,
    )


@router.post("/shift/{shift_id}/end")
async def end_shift(shift_id: uuid.UUID, body: EndShiftIn, principal: Principal = Depends(require_driver),
                    session: AsyncSession = Depends(get_session)) -> dict:
    await _own_shift(session, principal, shift_id)
    return await shifts_api.clock_out(
        shift_id,
        shifts_api.ClockOutRequest(
            odometer_out_km=body.odometer_km,
            fuel_level_out_pct=LEVEL_PCT.get(body.fuel_level) if body.fuel_level else None,
            adblue_level_out_pct=LEVEL_PCT.get(body.adblue_level) if body.adblue_level else None,
            notes=body.notes,
        ),
        session,
    )


# --- walkaround submit (also records the readings on the shift) ---------------------------------

@router.post("/walkaround", status_code=201)
async def submit_walkaround(body: walkaround_api.CheckIn, principal: Principal = Depends(require_driver),
                            session: AsyncSession = Depends(get_session)) -> dict:
    await _own_shift(session, principal, body.shift_id)
    body.driver_name = principal.name
    result = await walkaround_api.submit_check(body, session)
    if body.shift_id and body.phase in ("pre_use", "end_of_day"):
        shift = (await session.execute(select(Shift).where(Shift.id == body.shift_id))).scalar_one_or_none()
        if shift is not None:
            if body.phase == "pre_use":
                shift.odometer_km = body.odometer_km if body.odometer_km is not None else shift.odometer_km
                if body.fuel_level:
                    shift.fuel_level_pct = LEVEL_PCT[body.fuel_level]
                if body.adblue_level:
                    shift.adblue_level_pct = LEVEL_PCT[body.adblue_level]
            else:
                shift.odometer_out_km = body.odometer_km if body.odometer_km is not None else shift.odometer_out_km
                if body.fuel_level:
                    shift.fuel_level_out_pct = LEVEL_PCT[body.fuel_level]
                if body.adblue_level:
                    shift.adblue_level_out_pct = LEVEL_PCT[body.adblue_level]
            await session.commit()
    return result


# --- uploads: fuel, faults, paperwork ----------------------------------------------------------

async def _save_upload(file: UploadFile | None) -> dict | None:
    if file is None or not file.filename:
        return None
    raw = await file.read()
    if not raw:
        return None
    if len(raw) > _MAX_UPLOAD:
        raise HTTPException(status_code=400, detail="File too large (max 10 MB).")
    ct = (file.content_type or "application/octet-stream").lower()
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "application/pdf": "pdf"}.get(ct)
    if ext is None:
        raise HTTPException(status_code=400, detail="Upload a photo (JPEG/PNG/WebP) or a PDF.")
    path = media_store._root() / f"{uuid.uuid4().hex}.{ext}"
    path.write_bytes(raw)
    return {"storage_path": str(path), "content_type": ct}


def _dec(v: str | None) -> Decimal | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        return Decimal(str(v).strip())
    except Exception:
        raise HTTPException(status_code=400, detail=f"Not a number: {v}")


@router.post("/fuel", status_code=201)
async def add_fuel(
    vehicle_reg: str = Form(...),
    driver_name: str | None = Form(None),  # ignored: the signed-in driver is used
    fuel_type: str = Form("diesel"),
    litres: str | None = Form(None),
    cost: str | None = Form(None),
    odometer_km: int | None = Form(None),
    full_tank: bool = Form(True),
    location: str | None = Form(None),
    shift_id: uuid.UUID | None = Form(None),
    receipt: UploadFile | None = File(None),
    principal: Principal = Depends(require_driver),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _own_shift(session, principal, shift_id)
    driver_name = principal.name
    if fuel_type not in ("diesel", "adblue", "petrol", "electric"):
        raise HTTPException(status_code=400, detail="Unknown fuel type.")
    meta = await _save_upload(receipt)
    log = FuelLog(
        vehicle_reg=norm_reg(vehicle_reg), driver_name=driver_name.strip(), fuel_type=fuel_type,
        litres=_dec(litres), cost=_dec(cost), odometer_km=odometer_km, full_tank=full_tank,
        location=location, shift_id=shift_id,
        receipt_path=meta["storage_path"] if meta else None,
        content_type=meta["content_type"] if meta else None,
    )
    session.add(log)
    await session.commit()
    return {"id": str(log.id), "ok": True}


@router.post("/faults", status_code=201)
async def report_fault(
    vehicle_reg: str = Form(...),
    driver_name: str | None = Form(None),  # ignored: the signed-in driver is used
    item: str = Form(...),
    severity: str = Form("major"),
    description: str | None = Form(None),
    shift_id: uuid.UUID | None = Form(None),
    photo: UploadFile | None = File(None),
    principal: Principal = Depends(require_driver),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """An ad-hoc fault outside a walkaround. Stored as a one-defect walkaround check
    (phase=fault_report) so it lands on the manager's existing defects board."""
    await _own_shift(session, principal, shift_id)
    driver_name = principal.name
    if severity not in ("dangerous", "major", "minor"):
        raise HTTPException(status_code=400, detail="Unknown severity.")
    reg = norm_reg(vehicle_reg)
    check = WalkaroundCheck(
        vehicle_reg=reg, driver_name=driver_name.strip(), phase="fault_report", result="defects",
        safe_to_drive=severity == "minor", notes=description, shift_id=shift_id,
    )
    session.add(check)
    await session.flush()
    session.add(WalkaroundDefect(check_id=check.id, vehicle_reg=reg, item=item.strip()[:80],
                                 severity=severity, description=description, reported_by=driver_name.strip()))
    meta = await _save_upload(photo)
    if meta:
        session.add(WalkaroundPhoto(check_id=check.id, item=item.strip()[:80],
                                    content_type=meta["content_type"], storage_path=meta["storage_path"]))
    await session.commit()
    return {"id": str(check.id), "ok": True}


@router.post("/paperwork", status_code=201)
async def upload_paperwork(
    driver_name: str | None = Form(None),  # ignored: the signed-in driver is used
    kind: str = Form("other"),
    vehicle_reg: str | None = Form(None),
    note: str | None = Form(None),
    job_id: uuid.UUID | None = Form(None),
    shift_id: uuid.UUID | None = Form(None),
    file: UploadFile = File(...),
    principal: Principal = Depends(require_driver),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _own_shift(session, principal, shift_id)
    driver_name = principal.name
    if job_id is not None:
        job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        ensure_own(principal, job.driver_name)
    if kind not in ("job_sheet", "pod", "receipt", "other"):
        raise HTTPException(status_code=400, detail="Unknown paperwork type.")
    meta = await _save_upload(file)
    if meta is None:
        raise HTTPException(status_code=400, detail="Choose a photo or PDF to upload.")
    doc = DriverPaperwork(
        driver_name=driver_name.strip(), kind=kind, vehicle_reg=norm_reg(vehicle_reg) or None,
        note=note, job_id=job_id, shift_id=shift_id,
        storage_path=meta["storage_path"], content_type=meta["content_type"],
    )
    session.add(doc)
    await session.commit()
    return {"id": str(doc.id), "ok": True}


# --- documents tab, files, contacts, history -------------------------------------------------------

@router.get("/documents")
async def documents(days: int = Query(30, ge=1, le=365), principal: Principal = Depends(require_driver),
                    session: AsyncSession = Depends(get_session)) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    name = principal.name
    papers = (await session.execute(
        select(DriverPaperwork).where(DriverPaperwork.driver_name.ilike(name), DriverPaperwork.created_at >= since)
        .order_by(DriverPaperwork.created_at.desc())
    )).scalars().all()
    checks = (await session.execute(
        select(WalkaroundCheck).where(WalkaroundCheck.driver_name.ilike(name), WalkaroundCheck.created_at >= since)
        .order_by(WalkaroundCheck.created_at.desc())
    )).scalars().all()
    fuel = (await session.execute(
        select(FuelLog).where(FuelLog.driver_name.ilike(name), FuelLog.created_at >= since)
        .order_by(FuelLog.created_at.desc())
    )).scalars().all()
    return {
        "paperwork": [{"id": str(p.id), "kind": p.kind, "vehicle_reg": p.vehicle_reg, "note": p.note,
                       "content_type": p.content_type,
                       "created_at": p.created_at.isoformat() if p.created_at else None} for p in papers],
        "walkarounds": [{"id": str(c.id), "vehicle_reg": c.vehicle_reg, "phase": c.phase, "result": c.result,
                         "created_at": c.created_at.isoformat() if c.created_at else None} for c in checks],
        "fuel": [{"id": str(f.id), "vehicle_reg": f.vehicle_reg, "fuel_type": f.fuel_type,
                  "litres": float(f.litres) if f.litres is not None else None,
                  "cost": float(f.cost) if f.cost is not None else None,
                  "has_receipt": bool(f.receipt_path),
                  "created_at": f.created_at.isoformat() if f.created_at else None} for f in fuel],
    }


@router.get("/files/{kind}/{file_id}")
async def get_file(kind: str, file_id: uuid.UUID, principal: Principal = Depends(require_driver),
                   session: AsyncSession = Depends(get_session)) -> Response:
    if kind == "paperwork":
        row = (await session.execute(select(DriverPaperwork).where(DriverPaperwork.id == file_id))).scalar_one_or_none()
        path, ct = (row.storage_path, row.content_type) if row else (None, None)
    elif kind == "fuel":
        row = (await session.execute(select(FuelLog).where(FuelLog.id == file_id))).scalar_one_or_none()
        path, ct = (row.receipt_path, row.content_type) if row else (None, None)
    else:
        raise HTTPException(status_code=404, detail="Unknown file kind.")
    if not path:
        raise HTTPException(status_code=404, detail="File not found.")
    ensure_own(principal, row.driver_name)
    try:
        return Response(content=media_store.read(path), media_type=ct or "application/octet-stream")
    except OSError:
        raise HTTPException(status_code=404, detail="File missing.")


@router.get("/contacts")
async def contacts() -> list[dict]:
    out = []
    for entry in (settings.driver_contacts or "").split(";"):
        parts = [p.strip() for p in entry.split("|")]
        if parts and parts[0]:
            out.append({"name": parts[0], "role": parts[1] if len(parts) > 1 else "",
                        "phone": parts[2] if len(parts) > 2 else ""})
    return out


@router.get("/history")
async def history(limit: int = Query(20, ge=1, le=100), principal: Principal = Depends(require_driver),
                  session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.execute(
        select(Shift).where(func.lower(Shift.driver_name) == principal.name.lower())
        .order_by(Shift.clocked_in_at.desc()).limit(limit)
    )).scalars().all()
    return [shifts_api._shift_summary(s) for s in rows]

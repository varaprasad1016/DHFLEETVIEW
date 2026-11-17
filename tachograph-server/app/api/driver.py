"""Driver mobile app API (the "Live" screen at /tacho/driver).

Composes the existing shift, job and walkaround records into what a driver
sees on one screen — the vehicle they're on, whether today's pre-use and
end-of-day checks are done, open faults and their jobs — and adds the driver
actions that had no home yet: fuel fill-ups, ad-hoc fault reports and paperwork
uploads. Licence-gated like the rest of the compliance suite.
"""

from __future__ import annotations

import uuid
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import shifts as shifts_api
from app.api import walkaround as walkaround_api
from app.api.deps import Scope, record_scope, require_driver, require_license, require_module
from app.config import settings
from app.database import get_session
from app.models.core import Company, Device, Vehicle
from app.models.driver_app import DriverPaperwork, FuelLog
from app.models.driver_auth import DriverAccount, DriverMembership
from app.models.tacho import Infringement, TachoActivity, TachoFile
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


async def _active_shift(session: AsyncSession, scope: Scope) -> Shift | None:
    return (await session.execute(
        select(Shift).where(scope.condition(Shift), Shift.status.in_(ACTIVE_SHIFT))
        .order_by(Shift.clocked_in_at.desc())
    )).scalars().first()


async def _companies(session: AsyncSession, principal: Principal) -> dict[int, str]:
    """This driver's active company links: DH FleetView driver id -> company label."""
    if not principal.driver_ids:
        return {}
    rows = (await session.execute(
        select(DriverMembership.traccar_driver_id, DriverMembership.company_label)
        .where(DriverMembership.traccar_driver_id.in_(principal.driver_ids), DriverMembership.active.is_(True))
        .order_by(DriverMembership.created_at)
    )).all()
    return {tid: (label or "Company") for tid, label in rows}


def _company_for(scope: Scope, shift: Shift | None) -> int | None:
    """Which company a new record belongs to: the shift's, else the only one."""
    if shift is not None and shift.traccar_driver_id is not None:
        return shift.traccar_driver_id
    ids = sorted(scope.driver_ids)
    return ids[0] if len(ids) == 1 else None


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


async def _driver_jobs(session: AsyncSession, scope: Scope, companies: dict[int, str]) -> list[dict]:
    today = _london_midnight(datetime.now(timezone.utc))
    rows = (await session.execute(
        select(Job).where(
            scope.condition(Job),
            or_(Job.status.in_(OPEN_JOB), Job.completed_at >= today),
        ).order_by(Job.scheduled_at.asc().nulls_last(), Job.assigned_at.asc())
    )).scalars().all()
    return [{**shifts_api._job_summary(j), "description": j.description,
             "pickup_location": j.pickup_location, "dropoff_location": j.dropoff_location,
             "company": companies.get(j.traccar_driver_id)} for j in rows]


async def _own_shift(session: AsyncSession, scope: Scope, shift_id: uuid.UUID | None) -> Shift | None:
    if shift_id is None:
        return None
    shift = (await session.execute(select(Shift).where(Shift.id == shift_id))).scalar_one_or_none()
    if shift is None or not scope.allows(shift.traccar_driver_id, shift.driver_name):
        raise HTTPException(status_code=404, detail="Shift not found.")
    return shift


@router.get("/state")
async def driver_state(principal: Principal = Depends(require_driver), scope: Scope = Depends(record_scope),
                       session: AsyncSession = Depends(get_session)) -> dict:
    name = principal.name
    shift = await _active_shift(session, scope)
    companies = await _companies(session, principal)
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
        "shift": ({**shifts_api._shift_summary(shift), "company": companies.get(shift.traccar_driver_id)}
                  if shift else None),
        "companies": [{"id": tid, "label": label} for tid, label in companies.items()],
        "vehicle": vehicle,
        "jobs": await _driver_jobs(session, scope, companies),
        "infringements_to_sign": sum(1 for i in await _my_infringements(session, principal) if i["needs_signature"]),
        "modules": {"jobs": True},
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


# --- shift start / end -------------------------------------------------------------------

class StartShiftIn(BaseModel):
    driver_name: str | None = None  # ignored: the signed-in driver is used
    vehicle_reg: str = Field(..., min_length=2, max_length=20)
    company_id: int | None = None   # which company (DH FleetView driver id) the driver is working for


class EndShiftIn(BaseModel):
    odometer_km: int | None = None
    fuel_level: str | None = Field(default=None, pattern="^(empty|1/4|1/2|3/4|full)$")
    adblue_level: str | None = Field(default=None, pattern="^(empty|1/4|1/2|3/4|full)$")
    notes: str | None = None


@router.post("/shift/start", status_code=201)
async def start_shift(body: StartShiftIn, principal: Principal = Depends(require_driver),
                      session: AsyncSession = Depends(get_session)) -> dict:
    ids = list(principal.driver_ids)
    if body.company_id is not None:
        if body.company_id not in ids:
            raise HTTPException(status_code=404, detail="Company not found.")
        company = body.company_id
    elif len(ids) == 1:
        company = ids[0]
    elif ids:
        raise HTTPException(status_code=400, detail="Choose which company you're driving for.")
    else:
        company = None
    shift = await shifts_api.create_shift(session, principal.name, company, norm_reg(body.vehicle_reg),
                                          same_person=principal.driver_ids)
    await session.commit()
    return shifts_api._shift_summary(shift)


@router.post("/shift/{shift_id}/end")
async def end_shift(shift_id: uuid.UUID, body: EndShiftIn, scope: Scope = Depends(record_scope),
                    session: AsyncSession = Depends(get_session)) -> dict:
    shift = await _own_shift(session, scope, shift_id)
    return await shifts_api.end_shift(
        session, shift,
        shifts_api.ClockOutRequest(
            odometer_out_km=body.odometer_km,
            fuel_level_out_pct=LEVEL_PCT.get(body.fuel_level) if body.fuel_level else None,
            adblue_level_out_pct=LEVEL_PCT.get(body.adblue_level) if body.adblue_level else None,
            notes=body.notes,
        ),
    )


# --- walkaround submit (also records the readings on the shift) ---------------------------------

@router.post("/walkaround", status_code=201)
async def submit_walkaround(body: walkaround_api.CheckIn, principal: Principal = Depends(require_driver),
                            scope: Scope = Depends(record_scope),
                            session: AsyncSession = Depends(get_session)) -> dict:
    own = await _own_shift(session, scope, body.shift_id)
    body.driver_name = principal.name
    result = await walkaround_api.submit_check(body, session)
    await session.execute(update(WalkaroundCheck).where(WalkaroundCheck.id == uuid.UUID(result["id"]))
                          .values(traccar_driver_id=_company_for(scope, own)))
    await session.commit()
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
    scope: Scope = Depends(record_scope),
    session: AsyncSession = Depends(get_session),
) -> dict:
    own = await _own_shift(session, scope, shift_id)
    driver_name = principal.name
    if fuel_type not in ("diesel", "adblue", "petrol", "electric"):
        raise HTTPException(status_code=400, detail="Unknown fuel type.")
    meta = await _save_upload(receipt)
    log = FuelLog(
        vehicle_reg=norm_reg(vehicle_reg), driver_name=driver_name.strip(), fuel_type=fuel_type,
        litres=_dec(litres), cost=_dec(cost), odometer_km=odometer_km, full_tank=full_tank,
        location=location, shift_id=shift_id, traccar_driver_id=_company_for(scope, own),
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
    scope: Scope = Depends(record_scope),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """An ad-hoc fault outside a walkaround. Stored as a one-defect walkaround check
    (phase=fault_report) so it lands on the manager's existing defects board."""
    own = await _own_shift(session, scope, shift_id)
    driver_name = principal.name
    if severity not in ("dangerous", "major", "minor"):
        raise HTTPException(status_code=400, detail="Unknown severity.")
    reg = norm_reg(vehicle_reg)
    check = WalkaroundCheck(
        vehicle_reg=reg, driver_name=driver_name.strip(), phase="fault_report", result="defects",
        safe_to_drive=severity == "minor", notes=description, shift_id=shift_id,
        traccar_driver_id=_company_for(scope, own),
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
    scope: Scope = Depends(record_scope),
    session: AsyncSession = Depends(get_session),
) -> dict:
    own = await _own_shift(session, scope, shift_id)
    driver_name = principal.name
    company = _company_for(scope, own)
    if job_id is not None:
        job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
        if job is None or not scope.allows(job.traccar_driver_id, job.driver_name):
            raise HTTPException(status_code=404, detail="Job not found.")
        company = job.traccar_driver_id if job.traccar_driver_id is not None else company
    if kind not in ("job_sheet", "pod", "receipt", "other"):
        raise HTTPException(status_code=400, detail="Unknown paperwork type.")
    meta = await _save_upload(file)
    if meta is None:
        raise HTTPException(status_code=400, detail="Choose a photo or PDF to upload.")
    doc = DriverPaperwork(
        driver_name=driver_name.strip(), kind=kind, vehicle_reg=norm_reg(vehicle_reg) or None,
        note=note, job_id=job_id, shift_id=shift_id, traccar_driver_id=company,
        storage_path=meta["storage_path"], content_type=meta["content_type"],
    )
    session.add(doc)
    await session.commit()
    return {"id": str(doc.id), "ok": True}


# --- documents tab, files, contacts, history -------------------------------------------------------

@router.get("/documents")
async def documents(days: int = Query(30, ge=1, le=365), scope: Scope = Depends(record_scope),
                    session: AsyncSession = Depends(get_session)) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    papers = (await session.execute(
        select(DriverPaperwork).where(scope.condition(DriverPaperwork), DriverPaperwork.created_at >= since)
        .order_by(DriverPaperwork.created_at.desc())
    )).scalars().all()
    checks = (await session.execute(
        select(WalkaroundCheck).where(scope.condition(WalkaroundCheck), WalkaroundCheck.created_at >= since)
        .order_by(WalkaroundCheck.created_at.desc())
    )).scalars().all()
    fuel = (await session.execute(
        select(FuelLog).where(scope.condition(FuelLog), FuelLog.created_at >= since)
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
async def get_file(kind: str, file_id: uuid.UUID, scope: Scope = Depends(record_scope),
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
    if not scope.allows(row.traccar_driver_id, row.driver_name):
        raise HTTPException(status_code=404, detail="File not found.")
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
async def history(limit: int = Query(20, ge=1, le=100), scope: Scope = Depends(record_scope),
                  session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.execute(
        select(Shift).where(scope.condition(Shift))
        .order_by(Shift.clocked_in_at.desc()).limit(limit)
    )).scalars().all()
    return [shifts_api._shift_summary(s) for s in rows]


# --- the driver's own tachograph data (Hours tab) ------------------------------------------------

def _card_key(value: str | None) -> str:
    """Driver card numbers compare on the 14-character driver identification
    (the last two characters are replacement/renewal indexes)."""
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())[:14]


async def _tacho_refs(session: AsyncSession, principal: Principal) -> tuple[str | None, list[str]]:
    """(card key, tachograph driver refs) for the signed-in driver. Linked only by
    driver card number, never by name, so nobody sees someone else's hours."""
    account = (await session.execute(
        select(DriverAccount).where(DriverAccount.id == uuid.UUID(principal.driver_id))
    )).scalar_one_or_none()
    key = _card_key(account.unique_id if account else None)
    if len(key) < 14:
        return None, []
    rows = (await session.execute(
        select(TachoFile.card_number, TachoFile.driver_ref)
        .where(TachoFile.file_kind == "driver_card", TachoFile.card_number.is_not(None), TachoFile.driver_ref.is_not(None))
    )).all()
    return key, sorted({ref for card, ref in rows if _card_key(card) == key})


@router.get("/tacho")
async def my_tacho(days: int = Query(28, ge=1, le=90), principal: Principal = Depends(require_driver),
                   session: AsyncSession = Depends(get_session)) -> dict:
    from app.services import tacho_live

    key, refs = await _tacho_refs(session, principal)
    if not key:
        return {"linked": False, "reason": "no_card_number"}
    now = datetime.now(timezone.utc)
    live_status = await tacho_live.status_for_card(session, key, now)
    if not refs and live_status is None and not await tacho_live.live_spans(session, key, now - timedelta(days=days), now=now):
        return {"linked": False, "reason": "no_card_downloads"}
    since = _london_midnight(now) - timedelta(days=days - 1)
    acts = (await session.execute(
        select(TachoActivity.activity_type, TachoActivity.started_at, TachoActivity.ended_at)
        .join(TachoFile, TachoFile.id == TachoActivity.source_file_id)
        .where(TachoFile.file_kind == "driver_card", TachoActivity.driver_ref.in_(refs), TachoActivity.ended_at >= since)
    )).all() if refs else []
    by_day = tacho_live.minutes_by_day([(t.lower(), max(s, since), e) for t, s, e in acts])
    # Live FMC650 data fills in the time since the last card download (the download wins where both exist).
    coverage = await tacho_live.download_coverage(session, key)
    live_from = max(since, coverage) if coverage else since
    live_days = tacho_live.minutes_by_day(await tacho_live.live_spans(session, key, live_from, now=now))
    for day, minutes in live_days.items():
        bucket = by_day.setdefault(day, {"drive": 0, "work": 0, "available": 0, "rest": 0})
        for kind, value in minutes.items():
            bucket[kind] += value
        bucket["live_minutes"] = bucket.get("live_minutes", 0) + sum(minutes.values())
    last_download = (await session.execute(
        select(func.max(TachoFile.created_at)).where(TachoFile.file_kind == "driver_card", TachoFile.driver_ref.in_(refs))
    )).scalar_one() if refs else None
    infringements = (await session.execute(
        select(Infringement).where(Infringement.driver_ref.in_(refs), Infringement.status == "open")
        .order_by(Infringement.period_start.desc()).limit(50)
    )).scalars().all() if refs else []
    week_start = _london_midnight(now) - timedelta(days=now.astimezone(LONDON).weekday())
    week_key = week_start.astimezone(LONDON).date().isoformat()
    return {
        "linked": True,
        "name": refs[0] if refs else (live_status.card_holder if live_status else principal.name),
        "last_card_download": last_download.isoformat() if last_download else None,
        "card_data_until": coverage.isoformat() if coverage else None,
        "live": tacho_live.status_view(live_status, now) if live_status else None,
        "days": [{"date": d, **v} for d, v in sorted(by_day.items(), reverse=True)],
        "this_week_drive_minutes": sum(v["drive"] for d, v in by_day.items() if d >= week_key),
        "infringements": [{"id": str(i.id), "title": i.title, "severity": i.severity, "detail": i.detail,
                           "period_start": i.period_start.isoformat(), "period_end": i.period_end.isoformat(),
                           "limit_minutes": i.limit_minutes, "actual_minutes": i.actual_minutes} for i in infringements],
    }


# --- the driver's own licence / qualification expiries -------------------------------------------

@router.get("/my-records")
async def my_records(principal: Principal = Depends(require_driver), session: AsyncSession = Depends(get_session)) -> dict:
    """Licence, Driver CPC, tachograph card, medical and ADR dates the office holds for this driver."""
    from app.api import driver_records as records_api
    from app.models.driver_records import DriverCpcCourse, DriverRecord

    account = (await session.execute(select(DriverAccount).where(DriverAccount.id == uuid.UUID(principal.driver_id)))).scalar_one_or_none()
    ids = list(principal.driver_ids)
    records = (await session.execute(select(DriverRecord).where(DriverRecord.traccar_driver_id.in_(ids or [-1]))
                                     .order_by(DriverRecord.updated_at.desc()))).scalars().all()
    record = records[0] if records else None
    courses = (await session.execute(select(DriverCpcCourse).where(DriverCpcCourse.traccar_driver_id.in_(ids or [-1])))).scalars().all()
    view = records_api._view({"id": record.traccar_driver_id if record else 0, "name": principal.name,
                              "uniqueId": account.unique_id if account else None},
                             record, list(courses), await records_api._card_expiries(session), datetime.now(timezone.utc).date())
    items = [i for i in view["items"].values() if i["status"] != "not_applicable"]
    return {"items": items, "attention": sum(1 for i in items if i["status"] in ("expired", "overdue", "due_soon"))}


# --- infringement sign-off -----------------------------------------------------------------

class SignInfringementIn(BaseModel):
    signature: str = Field(..., min_length=50)            # PNG data URL from the signature pad
    comment: str | None = Field(default=None, max_length=2000)


async def _my_infringements(session: AsyncSession, principal: Principal) -> list[dict]:
    """The driver's own infringements (linked by driver card), newest first, with sign-off state.
    Types the administrator leaves off everyone's weekly report aren't asked for."""
    from app.services import infringement_reviews, report_settings

    _, refs = await _tacho_refs(session, principal)
    if not refs:
        return []
    hidden, _ = await report_settings.hidden_for(session, None)
    rows = (await session.execute(
        select(Infringement).where(Infringement.driver_ref.in_(refs), Infringement.status != "dismissed")
        .order_by(Infringement.period_start.desc()).limit(200)
    )).scalars().all()
    rows = [r for r in rows if r.rule not in hidden]
    reviews = await infringement_reviews.reviews_for(session, [r.id for r in rows])
    out = []
    for r in rows:
        review = reviews.get(r.id)
        out.append({
            "id": str(r.id), "rule": r.rule, "title": r.title, "severity": r.severity, "detail": r.detail,
            "period_start": r.period_start.isoformat(), "period_end": r.period_end.isoformat(),
            "limit_minutes": r.limit_minutes, "actual_minutes": r.actual_minutes,
            "needs_signature": not (review and review.driver_signed_at),
            "review": infringement_reviews.view(review),
        })
    return out


@router.get("/infringements")
async def my_infringements(principal: Principal = Depends(require_driver),
                           session: AsyncSession = Depends(get_session)) -> list[dict]:
    return await _my_infringements(session, principal)


@router.post("/infringements/{inf_id}/sign")
async def sign_infringement(inf_id: uuid.UUID, body: SignInfringementIn, principal: Principal = Depends(require_driver),
                            session: AsyncSession = Depends(get_session)) -> dict:
    """The driver confirms they've been told about an infringement."""
    from app.models.infringement_review import InfringementReview
    from app.services import infringement_reviews

    mine = {i["id"]: i for i in await _my_infringements(session, principal)}
    if str(inf_id) not in mine:
        raise HTTPException(status_code=404, detail="Infringement not found.")
    review = (await infringement_reviews.reviews_for(session, [inf_id])).get(inf_id)
    if review and review.driver_signed_at:
        raise HTTPException(status_code=409, detail="You've already signed for this one.")
    try:
        stored = media_store.save_data_url(body.signature)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Signature couldn't be saved: {exc}")
    if review is None:
        review = InfringementReview(infringement_id=inf_id)
        session.add(review)
    now = datetime.now(timezone.utc)
    review.driver_account_id = uuid.UUID(principal.driver_id)
    review.driver_name = principal.name
    review.driver_signed_at = now
    review.driver_signature_path = stored["storage_path"]
    review.driver_comment = (body.comment or "").strip() or None
    review.updated_at = now
    await session.commit()
    return {"id": str(inf_id), "review": infringement_reviews.view(review)}


@router.get("/tacho/timeline.pdf")
async def my_tacho_pdf(days: int = Query(28, ge=1, le=90), principal: Principal = Depends(require_driver),
                       session: AsyncSession = Depends(get_session)) -> Response:
    """The driver's own activity as a timeline.

    The window is the last `days`, but anchored on the card rather than on
    today. A card downloaded in September can easily hold nothing newer than
    June, and asking for the last 28 days from now then produces a PDF with
    nothing on it - which reads as a broken button, not as "your card is out of
    date". So when the recent window is empty the same length of time is taken
    from the end of the card instead, and a card with nothing on it at all is
    said out loud rather than drawn as a blank page.
    """
    from app.api import tacho as tacho_api
    from app.services.tacho_scope import scope_for_card

    _, refs = await _tacho_refs(session, principal)
    if not refs:
        raise HTTPException(status_code=404, detail="No tachograph card data linked to your ID yet.")

    account = (await session.execute(
        select(DriverAccount).where(DriverAccount.id == uuid.UUID(principal.driver_id)))).scalar_one_or_none()
    own = await scope_for_card(session, account.unique_id if account else None)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    if not await tacho_api.timeline_rows(session, own, refs[0], start, end):
        latest = (await session.execute(
            select(func.max(TachoActivity.ended_at))
            .join(TachoFile, TachoFile.id == TachoActivity.source_file_id)
            .where(TachoFile.file_kind == "driver_card", own.activities(),
                   TachoActivity.driver_ref == refs[0]))).scalar_one_or_none()
        if latest is None:
            raise HTTPException(
                status_code=404,
                detail="There is no activity on your card yet. Hand it in for downloading "
                       "and it will appear here.")
        end, start = latest, latest - timedelta(days=days)

    return await tacho_api.timeline_pdf_response(session, own, refs[0], start, end)

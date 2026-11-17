"""Maintenance planner API (licence + office user + "maintenance" module).

Vehicles are the DH FleetView vehicles the office user can see.

GET    /api/maintenance/vehicles                     every vehicle with its schedule status
GET    /api/maintenance/vehicles/{device_id}          schedules, records and open defects
PUT    /api/maintenance/vehicles/{device_id}/schedules replace the vehicle's recurring items
POST   /api/maintenance/vehicles/{device_id}/records  record an inspection / test / service
GET    /api/maintenance/records/{id}/document         the uploaded inspection sheet
DELETE /api/maintenance/records/{id}
GET    /api/maintenance/upcoming?days=56              everything due, soonest first
GET    /api/maintenance/summary                       counts for the compliance hub
GET    /api/maintenance/presets                       suggested schedules by vehicle type
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_license, require_manager, require_module
from app.database import get_session
from app.models.maintenance import MaintenanceRecord, MaintenanceSchedule
from app.models.vehicle import VehicleStatus
from app.models.walkaround import WalkaroundDefect
from app.services import auth, media_store
from app.services.auth import Principal
from app.services.tacho_scope import primary_reg, reg_key

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"],
                   dependencies=[Depends(require_license), Depends(require_manager), Depends(require_module("maintenance"))])

KINDS = {
    "pmi": "Safety inspection (PMI)",
    "brake_test": "Brake performance test",
    "mot": "MOT / annual test",
    "tacho_calibration": "Tachograph calibration",
    "loler": "LOLER inspection",
    "tail_lift": "Tail lift inspection",
    "service": "Service",
    "tyres": "Tyre check",
    "other": "Other",
}
# How long before the due date an item counts as "due soon".
DUE_SOON_DAYS = {"pmi": 7, "brake_test": 7, "tyres": 7}
DEFAULT_DUE_SOON = 30
PRESETS = {
    "hgv": [("pmi", "Safety inspection (PMI)", 6, "weeks"), ("mot", "MOT / annual test", 12, "months"),
            ("tacho_calibration", "Tachograph calibration", 24, "months")],
    "trailer": [("pmi", "Safety inspection (PMI)", 6, "weeks"), ("mot", "MOT / annual test", 12, "months")],
    "van": [("service", "Service", 12, "months"), ("mot", "MOT / annual test", 12, "months")],
    "tail_lift": [("loler", "LOLER inspection", 6, "months")],
}


class ScheduleIn(BaseModel):
    kind: str
    label: str | None = Field(default=None, max_length=80)
    interval_value: int = Field(ge=1, le=120)
    interval_unit: str = Field(pattern="^(weeks|months)$")
    next_due: date | None = None
    active: bool = True


class SchedulesIn(BaseModel):
    schedules: list[ScheduleIn]


class RecordIn(BaseModel):
    schedule_id: uuid.UUID | None = None
    kind: str
    label: str | None = Field(default=None, max_length=80)
    performed_on: date
    performed_by: str | None = Field(default=None, max_length=160)
    odometer_km: int | None = Field(default=None, ge=0)
    result: str | None = Field(default=None, pattern="^(pass|advisories|fail)$")
    brake_test_type: str | None = Field(default=None, pattern="^(roller_laden|roller_unladen|decelerometer|ebpms)$")
    brake_service_pct: float | None = Field(default=None, ge=0, le=100)
    brake_secondary_pct: float | None = Field(default=None, ge=0, le=100)
    brake_parking_pct: float | None = Field(default=None, ge=0, le=100)
    defects_found: str | None = Field(default=None, max_length=4000)
    notes: str | None = Field(default=None, max_length=4000)
    document: str | None = None                     # data URL (PDF or photo)
    document_name: str | None = Field(default=None, max_length=200)
    next_due: date | None = None                    # override the next due date


# --- helpers -------------------------------------------------------------------------------------

def add_interval(start: date, value: int, unit: str) -> date:
    if unit == "weeks":
        return start + timedelta(weeks=value)
    month = start.month - 1 + value
    year, month = start.year + month // 12, month % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def status_for(kind: str, next_due: date | None, today: date) -> tuple[str, int | None]:
    if next_due is None:
        return "not_scheduled", None
    days = (next_due - today).days
    if days < 0:
        return "overdue", days
    if days <= DUE_SOON_DAYS.get(kind, DEFAULT_DUE_SOON):
        return "due_soon", days
    return "ok", days


STATUS_ORDER = {"overdue": 0, "due_soon": 1, "not_scheduled": 2, "ok": 3}


async def visible_vehicles(principal: Principal) -> dict[int, dict]:
    path = "/api/devices?all=true" if principal.administrator else "/api/devices"
    devices = await auth.traccar_get(principal, path)
    return {int(d["id"]): d for d in (devices or []) if isinstance(d, dict) and "id" in d}


async def _vehicle(principal: Principal, device_id: int) -> dict:
    device = (await visible_vehicles(principal)).get(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Vehicle not found in your DH FleetView vehicles.")
    return device


def _schedule_view(s: MaintenanceSchedule, today: date) -> dict:
    st, days = status_for(s.kind, s.next_due, today)
    return {"id": str(s.id), "kind": s.kind, "kind_label": KINDS.get(s.kind, s.kind), "label": s.label,
            "interval_value": s.interval_value, "interval_unit": s.interval_unit,
            "next_due": s.next_due.isoformat() if s.next_due else None, "active": s.active,
            "status": st if s.active else "inactive", "days_left": days}


def _record_view(r: MaintenanceRecord) -> dict:
    num = lambda v: None if v is None else float(v)  # noqa: E731
    return {"id": str(r.id), "traccar_device_id": r.traccar_device_id, "registration": r.registration,
            "schedule_id": str(r.schedule_id) if r.schedule_id else None, "kind": r.kind,
            "kind_label": KINDS.get(r.kind, r.kind), "label": r.label,
            "due_on": r.due_on.isoformat() if r.due_on else None, "performed_on": r.performed_on.isoformat(),
            "on_time": None if r.due_on is None else r.performed_on <= r.due_on,
            "performed_by": r.performed_by, "odometer_km": r.odometer_km, "result": r.result,
            "brake_test_type": r.brake_test_type, "brake_service_pct": num(r.brake_service_pct),
            "brake_secondary_pct": num(r.brake_secondary_pct), "brake_parking_pct": num(r.brake_parking_pct),
            "defects_found": r.defects_found, "notes": r.notes, "has_document": bool(r.document_path),
            "document_name": r.document_name, "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None}


async def _open_defects(session: AsyncSession, regs: set[str]) -> dict[str, dict]:
    if not regs:
        return {}
    rows = (await session.execute(
        select(WalkaroundDefect.vehicle_reg, WalkaroundDefect.severity, func.count())
        .where(WalkaroundDefect.status == "open").group_by(WalkaroundDefect.vehicle_reg, WalkaroundDefect.severity)
    )).all()
    out: dict[str, dict] = {}
    for reg, severity, count in rows:
        key = reg_key(reg)
        if key in regs:
            bucket = out.setdefault(key, {"open": 0, "dangerous": 0})
            bucket["open"] += count
            if severity == "dangerous":
                bucket["dangerous"] += count
    return out


async def _mot(session: AsyncSession, regs: set[str]) -> dict[str, date | None]:
    if not regs:
        return {}
    rows = (await session.execute(select(VehicleStatus.reg, VehicleStatus.mot_expiry_date))).all()
    return {reg_key(r): d for r, d in rows if reg_key(r) in regs}


def _clean_kind(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"Unknown maintenance type: {kind}")
    return kind


# --- endpoints -----------------------------------------------------------------------------------

@router.get("/presets")
async def presets() -> dict:
    return {"kinds": [{"code": k, "label": v} for k, v in KINDS.items()],
            "presets": {name: [{"kind": k, "label": l, "interval_value": n, "interval_unit": u} for k, l, n, u in items]
                        for name, items in PRESETS.items()}}


@router.get("/vehicles")
async def list_vehicles(principal: Principal = Depends(require_manager),
                        session: AsyncSession = Depends(get_session)) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    vehicles = await visible_vehicles(principal)
    if not vehicles:
        return []
    schedules = (await session.execute(
        select(MaintenanceSchedule).where(MaintenanceSchedule.traccar_device_id.in_(list(vehicles)))
    )).scalars().all()
    last_records = dict((await session.execute(
        select(MaintenanceRecord.traccar_device_id, func.max(MaintenanceRecord.performed_on))
        .where(MaintenanceRecord.traccar_device_id.in_(list(vehicles)), MaintenanceRecord.kind == "pmi")
        .group_by(MaintenanceRecord.traccar_device_id))).all())
    regs = {primary_reg(d) for d in vehicles.values()} - {""}
    defects = await _open_defects(session, regs)
    mots = await _mot(session, regs)
    out = []
    for device_id, device in vehicles.items():
        reg = primary_reg(device)
        items = [_schedule_view(s, today) for s in schedules if s.traccar_device_id == device_id]
        active = [i for i in items if i["active"]]
        worst = min((i["status"] for i in active), key=lambda s: STATUS_ORDER.get(s, 9), default="not_scheduled")
        dfx = defects.get(reg, {"open": 0, "dangerous": 0})
        out.append({
            "traccar_device_id": device_id, "name": device.get("name"), "registration": reg or None,
            "schedules": sorted(items, key=lambda i: (i["next_due"] or "9999")),
            "status": worst,
            "last_pmi": last_records.get(device_id).isoformat() if last_records.get(device_id) else None,
            "open_defects": dfx["open"], "dangerous_defects": dfx["dangerous"],
            "mot_expiry": mots.get(reg).isoformat() if mots.get(reg) else None,
        })
    out.sort(key=lambda v: (STATUS_ORDER.get(v["status"], 9), (v["name"] or "").lower()))
    return out


@router.get("/vehicles/{device_id}")
async def vehicle_detail(device_id: int, principal: Principal = Depends(require_manager),
                         session: AsyncSession = Depends(get_session)) -> dict:
    device = await _vehicle(principal, device_id)
    today = datetime.now(timezone.utc).date()
    reg = primary_reg(device)
    mot = (await _mot(session, {reg})).get(reg) if reg else None
    schedules = (await session.execute(
        select(MaintenanceSchedule).where(MaintenanceSchedule.traccar_device_id == device_id)
        .order_by(MaintenanceSchedule.next_due.nulls_last()))).scalars().all()
    records = (await session.execute(
        select(MaintenanceRecord).where(MaintenanceRecord.traccar_device_id == device_id)
        .order_by(MaintenanceRecord.performed_on.desc(), MaintenanceRecord.created_at.desc()).limit(200))).scalars().all()
    open_defects = (await session.execute(
        select(WalkaroundDefect).where(WalkaroundDefect.status == "open",
                                       func.upper(func.replace(WalkaroundDefect.vehicle_reg, " ", "")) == (reg or "-"))
        .order_by(WalkaroundDefect.created_at.desc())
    )).scalars().all()
    return {
        "traccar_device_id": device_id, "name": device.get("name"), "registration": reg or None,
        "mot_expiry": mot.isoformat() if mot else None,
        "schedules": [_schedule_view(s, today) for s in schedules],
        "records": [_record_view(r) for r in records],
        "open_defects": [{"id": str(d.id), "item": d.item, "severity": d.severity, "description": d.description,
                          "reported_by": d.reported_by, "created_at": d.created_at.isoformat() if d.created_at else None}
                         for d in open_defects],
    }


@router.put("/vehicles/{device_id}/schedules")
async def save_schedules(device_id: int, body: SchedulesIn, principal: Principal = Depends(require_manager),
                         session: AsyncSession = Depends(get_session)) -> dict:
    device = await _vehicle(principal, device_id)
    reg = primary_reg(device) or None
    existing = (await session.execute(
        select(MaintenanceSchedule).where(MaintenanceSchedule.traccar_device_id == device_id))).scalars().all()
    by_key = {(s.kind, s.label): s for s in existing}
    keep = set()
    now = datetime.now(timezone.utc)
    for item in body.schedules:
        kind = _clean_kind(item.kind)
        label = (item.label or KINDS[kind]).strip()[:80]
        key = (kind, label)
        if key in keep:
            raise HTTPException(status_code=400, detail=f"'{label}' is listed twice.")
        keep.add(key)
        s = by_key.get(key)
        if s is None:
            s = MaintenanceSchedule(traccar_device_id=device_id, kind=kind, label=label)
            session.add(s)
        s.registration = reg
        s.interval_value, s.interval_unit = item.interval_value, item.interval_unit
        s.next_due, s.active = item.next_due, item.active
        s.updated_by, s.updated_at = principal.name, now
    for key, s in by_key.items():
        if key not in keep:
            await session.delete(s)          # records keep their history (schedule_id set null)
    await session.commit()
    return await vehicle_detail(device_id, principal, session)


@router.post("/vehicles/{device_id}/records", status_code=201)
async def add_record(device_id: int, body: RecordIn, principal: Principal = Depends(require_manager),
                     session: AsyncSession = Depends(get_session)) -> dict:
    device = await _vehicle(principal, device_id)
    kind = _clean_kind(body.kind)
    if body.performed_on > datetime.now(timezone.utc).date() + timedelta(days=1):
        raise HTTPException(status_code=400, detail="The date carried out can't be in the future.")
    schedule = None
    if body.schedule_id:
        schedule = await session.get(MaintenanceSchedule, body.schedule_id)
        if schedule is None or schedule.traccar_device_id != device_id:
            raise HTTPException(status_code=404, detail="Schedule not found for this vehicle.")
        kind = schedule.kind
    stored = None
    if body.document:
        try:
            stored = media_store.save_document(body.document)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Document couldn't be saved: {exc}")
    record = MaintenanceRecord(
        traccar_device_id=device_id, registration=primary_reg(device) or None,
        schedule_id=schedule.id if schedule else None, kind=kind,
        label=(schedule.label if schedule else (body.label or KINDS[kind]))[:80],
        due_on=schedule.next_due if schedule else None, performed_on=body.performed_on,
        performed_by=body.performed_by, odometer_km=body.odometer_km, result=body.result,
        brake_test_type=body.brake_test_type, brake_service_pct=body.brake_service_pct,
        brake_secondary_pct=body.brake_secondary_pct, brake_parking_pct=body.brake_parking_pct,
        defects_found=body.defects_found, notes=body.notes,
        document_path=stored["storage_path"] if stored else None,
        document_name=(body.document_name or f"{kind}-{body.performed_on}")[:200] if stored else None,
        document_type=stored["content_type"] if stored else None, created_by=principal.name)
    session.add(record)
    if schedule:
        # Next one is due an interval after this one was done, unless the office sets the date.
        schedule.next_due = body.next_due or add_interval(body.performed_on, schedule.interval_value, schedule.interval_unit)
        schedule.updated_by, schedule.updated_at = principal.name, datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(record)
    return {"record": _record_view(record),
            "next_due": schedule.next_due.isoformat() if schedule and schedule.next_due else None}


async def _visible_record(session: AsyncSession, principal: Principal, record_id: uuid.UUID) -> MaintenanceRecord:
    record = await session.get(MaintenanceRecord, record_id)
    if record is None or record.traccar_device_id not in await visible_vehicles(principal):
        raise HTTPException(status_code=404, detail="Record not found.")
    return record


@router.get("/records/{record_id}/document")
async def record_document(record_id: uuid.UUID, principal: Principal = Depends(require_manager),
                          session: AsyncSession = Depends(get_session)) -> Response:
    record = await _visible_record(session, principal, record_id)
    if not record.document_path:
        raise HTTPException(status_code=404, detail="No document on this record.")
    ext = {"application/pdf": "pdf", "image/png": "png", "image/webp": "webp"}.get(record.document_type or "", "jpg")
    name = "".join(c if c.isalnum() or c in "-_." else "_" for c in (record.document_name or "document"))
    if not name.lower().endswith("." + ext):
        name += "." + ext
    return Response(content=media_store.read(record.document_path), media_type=record.document_type or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


@router.delete("/records/{record_id}")
async def delete_record(record_id: uuid.UUID, principal: Principal = Depends(require_manager),
                        session: AsyncSession = Depends(get_session)) -> dict:
    record = await _visible_record(session, principal, record_id)
    await session.delete(record)
    await session.commit()
    return {"deleted": True}


@router.get("/upcoming")
async def upcoming(days: int = Query(56, ge=1, le=400), principal: Principal = Depends(require_manager),
                   session: AsyncSession = Depends(get_session)) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    vehicles = await visible_vehicles(principal)
    if not vehicles:
        return []
    rows = (await session.execute(
        select(MaintenanceSchedule).where(MaintenanceSchedule.traccar_device_id.in_(list(vehicles)),
                                          MaintenanceSchedule.active.is_(True), MaintenanceSchedule.next_due.is_not(None),
                                          MaintenanceSchedule.next_due <= today + timedelta(days=days))
        .order_by(MaintenanceSchedule.next_due))).scalars().all()
    return [{**_schedule_view(s, today), "traccar_device_id": s.traccar_device_id,
             "vehicle": vehicles[s.traccar_device_id].get("name"), "registration": primary_reg(vehicles[s.traccar_device_id]) or None}
            for s in rows]


@router.get("/summary")
async def summary(principal: Principal = Depends(require_manager), session: AsyncSession = Depends(get_session)) -> dict:
    vehicles = await list_vehicles(principal, session)
    items = [s for v in vehicles for s in v["schedules"] if s["active"]]
    since = datetime.now(timezone.utc).date() - timedelta(days=365)
    pmis = (await session.execute(
        select(MaintenanceRecord.performed_on, MaintenanceRecord.due_on).where(
            MaintenanceRecord.traccar_device_id.in_([v["traccar_device_id"] for v in vehicles] or [-1]),
            MaintenanceRecord.kind == "pmi", MaintenanceRecord.performed_on >= since, MaintenanceRecord.due_on.is_not(None))
    )).all()
    on_time = sum(1 for done, due in pmis if done <= due)
    return {
        "vehicles": len(vehicles),
        "overdue": sum(1 for s in items if s["status"] == "overdue"),
        "due_soon": sum(1 for s in items if s["status"] == "due_soon"),
        "not_scheduled": sum(1 for v in vehicles if not v["schedules"]),
        "open_defects": sum(v["open_defects"] for v in vehicles),
        "pmi_on_time_pct": round(100 * on_time / len(pmis), 1) if pmis else None,
        "pmis_last_12_months": len(pmis),
    }

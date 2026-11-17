"""Driver shift and job management API.

Provides clock-in/out with odometer/fuel/AdBlue photo capture, break tracking,
and a job assignment workflow where owners send jobs and drivers accept/deny.

Every record is scoped to a company: it carries the company's DH FleetView
driver record (traccar_driver_id). Office users only see records for the drivers
linked to their account; drivers only see their own (see deps.Scope).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (Scope, ensure_scope, record_scope, require_driver_or_manager, require_license,
                          require_manager, require_module)
from app.config import settings
from app.database import get_session
from app.models.shifts import Shift, ShiftPhoto, Job, JobMessage, ShiftJob
from app.services import auth as auth_service
from app.services import media_store
from app.services.auth import Principal

router = APIRouter(prefix="/api/shifts", tags=["shifts"], dependencies=[Depends(require_license)])
MANAGER = [Depends(require_manager)]
SHIFTS = MANAGER + [Depends(require_module("shifts"))]
JOBS = MANAGER + [Depends(require_module("jobs"))]
JOBS_ANY = [Depends(require_module("jobs"))]
ACTIVE = ("clocked_in", "on_break", "active")


# --- Pydantic request models ---

class ClockInPhoto(BaseModel):
    photo_type: str = Field(..., pattern="^(odometer|fuel|adblue)$")
    image: str  # base64 data URL


class ClockInRequest(BaseModel):
    driver_name: str | None = None
    traccar_driver_id: int | None = None
    vehicle_reg: str | None = None
    odometer_km: int | None = None
    fuel_level_pct: int | None = None
    adblue_level_pct: int | None = None
    photos: list[ClockInPhoto] = []
    notes: str | None = None


class ClockOutRequest(BaseModel):
    odometer_out_km: int | None = None
    fuel_level_out_pct: int | None = None
    adblue_level_out_pct: int | None = None
    photos: list[ClockInPhoto] = []
    notes: str | None = None


class JobCreateRequest(BaseModel):
    traccar_driver_id: int | None = None   # the company's DH FleetView driver (preferred)
    driver_name: str | None = None         # legacy/typed name when not a DH FleetView driver
    vehicle_reg: str | None = None
    title: str
    description: str | None = None
    pickup_location: str | None = None
    dropoff_location: str | None = None
    priority: str = Field(default="normal", pattern="^(low|normal|urgent)$")
    scheduled_at: datetime | None = None


class JobActionRequest(BaseModel):
    reason: str | None = None


class JobMessageRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)
    author: str | None = None
    sender: str = Field(default="driver", pattern="^(driver|office)$")
    kind: str = Field(default="message", pattern="^(message|change)$")


class BreakRequest(BaseModel):
    break_type: str = Field(default="start", pattern="^(start|end)$")


class JobResendRequest(BaseModel):
    traccar_driver_id: int | None = None
    driver_name: str | None = Field(default=None, max_length=100)  # both None = same driver
    scheduled_at: datetime | None = None


def _store(data_url: str) -> dict:
    try:
        return media_store.save_data_url(data_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad image: {e}")


def _store_upload(file: UploadFile) -> dict:
    """Save an uploaded file via multipart form."""
    import uuid as _uuid
    from pathlib import Path
    raw = file.file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5 MB)")
    ext = "jpg"
    ct = file.content_type or "image/jpeg"
    if "png" in ct:
        ext = "png"
    root = Path(settings.archive_path).parent / "walkaround"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{_uuid.uuid4().hex}.{ext}"
    path.write_bytes(raw)
    return {"storage_path": str(path), "content_type": ct}


async def _load(session: AsyncSession, model, record_id: uuid.UUID, scope: Scope, label: str):
    row = (await session.execute(select(model).where(model.id == record_id))).scalar_one_or_none()
    if row is None or not scope.allows(row.traccar_driver_id, row.driver_name):
        raise HTTPException(status_code=404, detail=f"{label} not found.")
    return row


async def _office_driver(principal: Principal, traccar_driver_id: int) -> dict:
    """A driver the office user can see in DH FleetView (i.e. one they added)."""
    drivers = await auth_service.visible_drivers(principal)
    driver = next((d for d in drivers if int(d["id"]) == int(traccar_driver_id)), None)
    if driver is None or not driver.get("name"):
        raise HTTPException(status_code=404, detail="Driver not found in your DH FleetView drivers.")
    return driver


async def _resolve_driver(principal: Principal, traccar_driver_id: int | None, driver_name: str | None) -> tuple[int, str]:
    """(DH FleetView driver id, name) for one of the office user's own drivers.
    Every new record is tagged with a driver id so it stays inside that company."""
    if traccar_driver_id is not None:
        driver = await _office_driver(principal, traccar_driver_id)
    else:
        wanted = " ".join((driver_name or "").split()).lower()
        if not wanted:
            raise HTTPException(status_code=400, detail="Choose a driver.")
        matches = [d for d in await auth_service.visible_drivers(principal)
                   if " ".join(str(d.get("name") or "").split()).lower() == wanted]
        if not matches:
            raise HTTPException(status_code=400, detail="That driver isn't in your DH FleetView drivers. Add them in Settings → Drivers first.")
        if len(matches) > 1:
            raise HTTPException(status_code=400, detail="More than one of your drivers has that name. Choose the driver from the list.")
        driver = matches[0]
    return int(driver["id"]), " ".join(str(driver["name"]).split())


# --- shared shift logic (also used by the driver screens) ---

async def create_shift(session: AsyncSession, driver_name: str, traccar_driver_id: int | None,
                       vehicle_reg: str | None, same_person: tuple[int, ...] = (), **readings) -> Shift:
    """same_person: every company record of this driver (a driver can't be on two shifts at once)."""
    ids = set(same_person) | ({traccar_driver_id} if traccar_driver_id is not None else set())
    untagged_same_name = and_(Shift.traccar_driver_id.is_(None), Shift.driver_name == driver_name)
    who = or_(Shift.traccar_driver_id.in_(ids), untagged_same_name) if ids else untagged_same_name
    existing = (await session.execute(
        select(Shift).where(who, Shift.status.in_(ACTIVE))
    )).scalars().first()
    if existing:
        raise HTTPException(status_code=400, detail="Driver already has an active shift.")
    shift = Shift(driver_name=driver_name, traccar_driver_id=traccar_driver_id, vehicle_reg=vehicle_reg,
                  status="clocked_in", **readings)
    session.add(shift)
    await session.flush()
    return shift


async def end_shift(session: AsyncSession, shift: Shift, body: ClockOutRequest) -> dict:
    if shift.status == "clocked_out":
        raise HTTPException(status_code=400, detail="Shift already clocked out.")
    shift.status = "clocked_out"
    shift.clocked_out_at = datetime.now(timezone.utc)
    shift.odometer_out_km = body.odometer_out_km
    shift.fuel_level_out_pct = body.fuel_level_out_pct
    shift.adblue_level_out_pct = body.adblue_level_out_pct
    if body.notes:
        shift.notes = (shift.notes or "") + f"\n[Out] {body.notes}"
    for p in body.photos:
        meta = _store(p.image)
        session.add(ShiftPhoto(shift_id=shift.id, photo_type=f"{p.photo_type}_out",
                               content_type=meta["content_type"], storage_path=meta["storage_path"]))
    await session.commit()
    return {"id": str(shift.id), "status": shift.status,
            "clocked_out_at": shift.clocked_out_at.isoformat() if shift.clocked_out_at else None}


# ======================================================================
#  Fixed-string routes MUST come before parameterised ones ({shift_id}).
# ======================================================================

@router.post("/clock-in", status_code=201, dependencies=SHIFTS)
async def clock_in(body: ClockInRequest, session: AsyncSession = Depends(get_session),
                   principal: Principal = Depends(require_manager)) -> dict:
    """Office clocks a driver in on their behalf."""
    driver_id, name = await _resolve_driver(principal, body.traccar_driver_id, body.driver_name)
    shift = await create_shift(session, name, driver_id, body.vehicle_reg,
                               odometer_km=body.odometer_km, fuel_level_pct=body.fuel_level_pct,
                               adblue_level_pct=body.adblue_level_pct, notes=body.notes)
    for p in body.photos:
        meta = _store(p.image)
        session.add(ShiftPhoto(shift_id=shift.id, photo_type=f"{p.photo_type}_in",
                               content_type=meta["content_type"], storage_path=meta["storage_path"]))
    await session.commit()
    return {"id": str(shift.id), "status": shift.status, "driver_name": shift.driver_name,
            "vehicle_reg": shift.vehicle_reg,
            "clocked_in_at": shift.clocked_in_at.isoformat() if shift.clocked_in_at else None}


@router.post("/{shift_id}/photos", dependencies=SHIFTS)
async def upload_photos(
    shift_id: uuid.UUID,
    photo_type: str = Query(..., pattern="^(odometer|fuel|adblue)_(in|out)$"),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    scope: Scope = Depends(record_scope),
) -> dict:
    shift = await _load(session, Shift, shift_id, scope, "Shift")
    meta = _store_upload(file)
    session.add(ShiftPhoto(shift_id=shift.id, photo_type=photo_type,
                           content_type=meta["content_type"], storage_path=meta["storage_path"]))
    await session.commit()
    return {"ok": True, "photo_type": photo_type}


@router.get("/active", dependencies=SHIFTS)
async def active_shifts(session: AsyncSession = Depends(get_session), scope: Scope = Depends(record_scope)) -> list[dict]:
    rows = (await session.execute(
        select(Shift).where(Shift.status.in_(ACTIVE), scope.condition(Shift)).order_by(Shift.clocked_in_at.desc())
    )).scalars().all()
    return [_shift_summary(s) for s in rows]


@router.get("/history", dependencies=SHIFTS)
async def shift_history(limit: int = 100, driver_name: str | None = None,
                        session: AsyncSession = Depends(get_session), scope: Scope = Depends(record_scope)) -> list[dict]:
    stmt = select(Shift).where(Shift.status == "clocked_out", scope.condition(Shift))
    if driver_name:
        stmt = stmt.where(Shift.driver_name.ilike(f"%{driver_name}%"))
    rows = (await session.execute(stmt.order_by(Shift.clocked_out_at.desc()).limit(min(limit, 500)))).scalars().all()
    return [_shift_summary(s) for s in rows]


# --- Jobs ---

@router.post("/jobs", status_code=201, dependencies=JOBS)
async def create_job(body: JobCreateRequest, session: AsyncSession = Depends(get_session),
                     principal: Principal = Depends(require_manager)) -> dict:
    """Office sends a job to one of their drivers."""
    driver_id, name = await _resolve_driver(principal, body.traccar_driver_id, body.driver_name)
    job = Job(driver_name=name, traccar_driver_id=driver_id, vehicle_reg=body.vehicle_reg,
              title=body.title, description=body.description, pickup_location=body.pickup_location,
              dropoff_location=body.dropoff_location, priority=body.priority, scheduled_at=body.scheduled_at,
              assigned_by=principal.name, status="pending")
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return _job_summary(job)


@router.get("/jobs", dependencies=JOBS)
async def list_jobs(status: str | None = None, driver_name: str | None = None,
                    session: AsyncSession = Depends(get_session), scope: Scope = Depends(record_scope)) -> list[dict]:
    stmt = select(Job).where(scope.condition(Job))
    if status:
        stmt = stmt.where(Job.status == status)
    if driver_name:
        stmt = stmt.where(Job.driver_name.ilike(f"%{driver_name}%"))
    rows = (await session.execute(stmt.order_by(Job.created_at.desc()).limit(200))).scalars().all()
    return [_job_summary(j) for j in rows]


@router.get("/jobs/{job_id}", dependencies=JOBS_ANY)
async def get_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                  scope: Scope = Depends(record_scope)) -> dict:
    job = await _load(session, Job, job_id, scope, "Job")
    return {
        **_job_summary(job),
        "description": job.description,
        "pickup_location": job.pickup_location,
        "dropoff_location": job.dropoff_location,
        "assigned_by": job.assigned_by,
        "deny_reason": job.deny_reason,
        "messages": await _job_messages(session, job.id),
    }


async def _job_messages(session: AsyncSession, job_id: uuid.UUID) -> list[dict]:
    rows = (await session.execute(
        select(JobMessage).where(JobMessage.job_id == job_id).order_by(JobMessage.created_at)
    )).scalars().all()
    return [{
        "id": str(m.id), "sender": m.sender, "author": m.author, "kind": m.kind,
        "body": m.body, "created_at": m.created_at.isoformat() if m.created_at else None,
    } for m in rows]


@router.post("/jobs/{job_id}/messages", status_code=201, dependencies=JOBS_ANY)
async def post_job_message(job_id: uuid.UUID, body: JobMessageRequest,
                           session: AsyncSession = Depends(get_session),
                           scope: Scope = Depends(record_scope)) -> list[dict]:
    job = await _load(session, Job, job_id, scope, "Job")
    principal = scope.principal
    # Sender and author come from the sign-in, not the request body.
    session.add(JobMessage(job_id=job.id, sender="office" if principal.is_manager else "driver",
                           author=principal.name, kind=body.kind, body=body.body.strip()))
    await session.commit()
    return await _job_messages(session, job.id)


@router.post("/jobs/{job_id}/start", dependencies=JOBS_ANY)
async def start_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                    scope: Scope = Depends(record_scope)) -> dict:
    job = await _load(session, Job, job_id, scope, "Job")
    if job.status != "accepted":
        raise HTTPException(status_code=400, detail=f"Job must be accepted first (currently {job.status}).")
    job.status = "in_progress"
    job.started_at = datetime.now(timezone.utc)
    await session.commit()
    return _job_summary(job)


@router.post("/jobs/{job_id}/accept", dependencies=JOBS_ANY)
async def accept_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                     scope: Scope = Depends(record_scope)) -> dict:
    job = await _load(session, Job, job_id, scope, "Job")
    if job.status != "pending":
        raise HTTPException(status_code=400, detail=f"Job is already {job.status}.")
    job.status = "accepted"
    job.accepted_at = datetime.now(timezone.utc)
    shift_query = select(Shift).where(Shift.status.in_(ACTIVE))
    shift_query = (shift_query.where(Shift.traccar_driver_id == job.traccar_driver_id) if job.traccar_driver_id is not None
                   else shift_query.where(Shift.driver_name == job.driver_name))
    shift = (await session.execute(shift_query)).scalars().first()
    if shift:
        session.add(ShiftJob(shift_id=shift.id, job_id=job.id))
    await session.commit()
    return _job_summary(job)


@router.post("/jobs/{job_id}/deny", dependencies=JOBS_ANY)
async def deny_job(job_id: uuid.UUID, body: JobActionRequest, session: AsyncSession = Depends(get_session),
                   scope: Scope = Depends(record_scope)) -> dict:
    job = await _load(session, Job, job_id, scope, "Job")
    if job.status != "pending":
        raise HTTPException(status_code=400, detail=f"Job is already {job.status}.")
    job.status = "denied"
    job.denied_at = datetime.now(timezone.utc)
    job.deny_reason = body.reason
    await session.commit()
    return _job_summary(job)


@router.post("/jobs/{job_id}/complete", dependencies=JOBS_ANY)
async def complete_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                       scope: Scope = Depends(record_scope)) -> dict:
    job = await _load(session, Job, job_id, scope, "Job")
    if job.status not in ("accepted", "in_progress"):
        raise HTTPException(status_code=400, detail=f"Job must be accepted first (currently {job.status}).")
    job.status = "completed"
    job.completed_at = datetime.now(timezone.utc)
    await session.commit()
    return _job_summary(job)


@router.post("/jobs/{job_id}/cancel", dependencies=JOBS)
async def cancel_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                     scope: Scope = Depends(record_scope)) -> dict:
    job = await _load(session, Job, job_id, scope, "Job")
    if job.status in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Job is already {job.status}.")
    job.status = "cancelled"
    await session.commit()
    return _job_summary(job)


@router.post("/jobs/{job_id}/resend", dependencies=JOBS)
async def resend_job(job_id: uuid.UUID, body: JobResendRequest, session: AsyncSession = Depends(get_session),
                     scope: Scope = Depends(record_scope)) -> dict:
    """Send a declined or cancelled job again, to the same or another of your drivers."""
    principal = scope.principal
    job = await _load(session, Job, job_id, scope, "Job")
    if job.status not in ("denied", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Only declined or cancelled jobs can be resent (this one is {job.status}).")
    new_id, new_name = job.traccar_driver_id, job.driver_name
    if body.traccar_driver_id is not None or (body.driver_name and body.driver_name.strip()):
        new_id, new_name = await _resolve_driver(principal, body.traccar_driver_id, body.driver_name)
    previous = f"declined by {job.driver_name}" + (f": {job.deny_reason}" if job.deny_reason else "") \
        if job.status == "denied" else "cancelled"
    note = f"Resent to {new_name} by {principal.name} (previously {previous})."
    job.driver_name, job.traccar_driver_id = new_name, new_id
    job.status = "pending"
    job.assigned_at = datetime.now(timezone.utc)
    job.assigned_by = principal.name
    job.accepted_at = job.denied_at = job.started_at = job.completed_at = None
    job.deny_reason = None
    if body.scheduled_at is not None:
        job.scheduled_at = body.scheduled_at
    for link in (await session.execute(select(ShiftJob).where(ShiftJob.job_id == job.id))).scalars().all():
        await session.delete(link)
    session.add(JobMessage(job_id=job.id, sender="office", author=principal.name, kind="message", body=note))
    await session.commit()
    return _job_summary(job)


@router.get("/drivers", dependencies=JOBS)
async def job_drivers(session: AsyncSession = Depends(get_session),
                      principal: Principal = Depends(require_manager)) -> list[dict]:
    """Drivers this user can send jobs to: the drivers linked to their DH FleetView
    account (the ones they added), never other companies' drivers."""
    from app.models.driver_auth import DriverAccount, DriverMembership

    try:
        drivers = await auth_service.visible_drivers(principal)
    except Exception:
        raise HTTPException(status_code=503, detail="Can't load drivers from DH FleetView. Try again shortly.")
    drivers = [d for d in drivers if d.get("name")]
    ids = [int(d["id"]) for d in drivers]
    access: dict[int, bool] = {}
    if ids:
        rows = (await session.execute(
            select(DriverMembership.traccar_driver_id, DriverMembership.active, DriverAccount.active)
            .join(DriverAccount, DriverAccount.id == DriverMembership.account_id)
            .where(DriverMembership.traccar_driver_id.in_(ids))
        )).all()
        access = {tid: bool(m_active and a_active) for tid, m_active, a_active in rows}
    # Live tachograph figures (FMC650) so the office can see who has the hours for a job.
    from app.services import tacho_live
    from app.services.tacho_scope import card_key

    live: dict[str, dict] = {}
    for status in await tacho_live.fresh_statuses(session):
        if status.card_number and card_key(status.card_number) not in live:
            view = tacho_live.status_view(status)
            if not view["stale"]:
                live[card_key(status.card_number)] = {
                    "activity": view["activity"], "vehicle": view["vehicle_name"] or view["vehicle_reg"],
                    "driving_left_today": view["figures"].get("driving_left_today"),
                    "driving_until_break": view["figures"].get("driving_until_break"),
                    "driving_left_week": view["figures"].get("driving_left_week")}
    out = [{"id": int(d["id"]), "name": " ".join(d["name"].split()), "unique_id": d.get("uniqueId"),
            "app_access": access.get(int(d["id"]), False),
            "live": live.get(card_key(d.get("uniqueId"))) if len(card_key(d.get("uniqueId"))) == 14 else None}
           for d in drivers]
    return sorted(out, key=lambda e: e["name"].lower())


# --- Photo endpoint (before /{shift_id}) ---

@router.get("/photos/{photo_id}", dependencies=SHIFTS)
async def get_photo(photo_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                    scope: Scope = Depends(record_scope)) -> Response:
    row = (await session.execute(
        select(ShiftPhoto, Shift).join(Shift, Shift.id == ShiftPhoto.shift_id).where(ShiftPhoto.id == photo_id)
    )).first()
    if row is None or not scope.allows(row[1].traccar_driver_id, row[1].driver_name):
        raise HTTPException(status_code=404, detail="Photo not found.")
    try:
        return Response(content=media_store.read(row[0].storage_path), media_type=row[0].content_type)
    except OSError:
        raise HTTPException(status_code=404, detail="Photo file missing.")


# --- Parameterised shift endpoints (LAST) ---

@router.get("/{shift_id}", dependencies=SHIFTS)
async def get_shift(shift_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                    scope: Scope = Depends(record_scope)) -> dict:
    shift = await _load(session, Shift, shift_id, scope, "Shift")
    photos = (await session.execute(select(ShiftPhoto).where(ShiftPhoto.shift_id == shift_id))).scalars().all()
    job_ids = [jl.job_id for jl in (await session.execute(select(ShiftJob).where(ShiftJob.shift_id == shift_id))).scalars().all()]
    jobs = []
    if job_ids:
        jobs = [_job_summary(j) for j in (await session.execute(select(Job).where(Job.id.in_(job_ids)))).scalars().all()]
    return {**_shift_summary(shift), "photos": [{"id": str(p.id), "photo_type": p.photo_type} for p in photos], "jobs": jobs}


@router.post("/{shift_id}/clock-out", dependencies=SHIFTS)
async def clock_out(shift_id: uuid.UUID, body: ClockOutRequest, session: AsyncSession = Depends(get_session),
                    scope: Scope = Depends(record_scope)) -> dict:
    shift = await _load(session, Shift, shift_id, scope, "Shift")
    return await end_shift(session, shift, body)


@router.post("/{shift_id}/break")
async def toggle_break(shift_id: uuid.UUID, body: BreakRequest, session: AsyncSession = Depends(get_session),
                       scope: Scope = Depends(record_scope)) -> dict:
    shift = await _load(session, Shift, shift_id, scope, "Shift")
    if shift.status == "clocked_out":
        raise HTTPException(status_code=400, detail="Shift is already clocked out.")
    now = datetime.now(timezone.utc)
    if body.break_type == "start":
        if shift.status == "on_break":
            raise HTTPException(status_code=400, detail="Already on break.")
        shift.status = "on_break"
        shift.break_started_at = now
    else:
        if shift.status != "on_break":
            raise HTTPException(status_code=400, detail="Not currently on break.")
        shift.status = "active"
        shift.break_ended_at = now
    await session.commit()
    return {"id": str(shift.id), "status": shift.status}


# --- Helpers ---

def _shift_summary(s: Shift) -> dict:
    return {
        "id": str(s.id),
        "driver_name": s.driver_name,
        "traccar_driver_id": s.traccar_driver_id,
        "vehicle_reg": s.vehicle_reg,
        "status": s.status,
        "odometer_km": s.odometer_km,
        "fuel_level_pct": s.fuel_level_pct,
        "adblue_level_pct": s.adblue_level_pct,
        "odometer_out_km": s.odometer_out_km,
        "fuel_level_out_pct": s.fuel_level_out_pct,
        "adblue_level_out_pct": s.adblue_level_out_pct,
        "clocked_in_at": s.clocked_in_at.isoformat() if s.clocked_in_at else None,
        "break_started_at": s.break_started_at.isoformat() if s.break_started_at else None,
        "break_ended_at": s.break_ended_at.isoformat() if s.break_ended_at else None,
        "clocked_out_at": s.clocked_out_at.isoformat() if s.clocked_out_at else None,
    }


def _job_summary(j: Job) -> dict:
    return {
        "id": str(j.id),
        "number": j.number,
        "ref": f"JOB-{j.number}" if j.number else None,
        "driver_name": j.driver_name,
        "traccar_driver_id": j.traccar_driver_id,
        "vehicle_reg": j.vehicle_reg,
        "title": j.title,
        "priority": j.priority,
        "status": j.status,
        "assigned_at": j.assigned_at.isoformat() if j.assigned_at else None,
        "accepted_at": j.accepted_at.isoformat() if j.accepted_at else None,
        "denied_at": j.denied_at.isoformat() if j.denied_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        "scheduled_at": j.scheduled_at.isoformat() if j.scheduled_at else None,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "deny_reason": j.deny_reason,
    }

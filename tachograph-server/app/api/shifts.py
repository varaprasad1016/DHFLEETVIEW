"""Driver shift and job management API.

Provides clock-in/out with odometer/fuel/AdBlue photo capture, break tracking,
and a job assignment workflow where owners send jobs and drivers accept/deny.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ensure_own, require_driver_or_manager, require_license, require_manager, require_module
from app.config import settings
from app.database import get_session
from app.models.shifts import Shift, ShiftPhoto, Job, JobMessage, ShiftJob
from app.services import media_store
from app.services.auth import Principal

router = APIRouter(prefix="/api/shifts", tags=["shifts"], dependencies=[Depends(require_license)])
MANAGER = [Depends(require_manager)]
SHIFTS = MANAGER + [Depends(require_module("shifts"))]
JOBS = MANAGER + [Depends(require_module("jobs"))]
JOBS_ANY = [Depends(require_module("jobs"))]


# --- Pydantic request models ---

class ClockInPhoto(BaseModel):
    photo_type: str = Field(..., pattern="^(odometer|fuel|adblue)$")
    image: str  # base64 data URL


class ClockInRequest(BaseModel):
    driver_name: str
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
    driver_name: str
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


def _store(data_url: str) -> dict:
    try:
        return media_store.save_data_url(data_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad image: {e}")


def _store_upload(file: UploadFile) -> dict:
    """Save an uploaded file via multipart form."""
    import base64, uuid as _uuid
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


# ======================================================================
#  Fixed-string routes MUST come before parameterised ones ({shift_id}).
#  FastAPI matches top-to-bottom; /jobs was being swallowed by /{shift_id}.
# ======================================================================

# --- Clock In ---

@router.post("/clock-in", status_code=201, dependencies=SHIFTS)
async def clock_in(body: ClockInRequest, session: AsyncSession = Depends(get_session)) -> dict:
    """Driver clocks in with vehicle readings and photos."""
    existing = (await session.execute(
        select(Shift).where(
            Shift.driver_name == body.driver_name,
            Shift.status.in_(["clocked_in", "on_break", "active"])
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Driver already has an active shift.")

    shift = Shift(
        driver_name=body.driver_name,
        vehicle_reg=body.vehicle_reg,
        odometer_km=body.odometer_km,
        fuel_level_pct=body.fuel_level_pct,
        adblue_level_pct=body.adblue_level_pct,
        notes=body.notes,
        status="clocked_in",
    )
    session.add(shift)
    await session.flush()

    for p in body.photos:
        meta = _store(p.image)
        session.add(ShiftPhoto(
            shift_id=shift.id,
            photo_type=f"{p.photo_type}_in",
            content_type=meta["content_type"],
            storage_path=meta["storage_path"],
        ))

    await session.commit()
    return {
        "id": str(shift.id),
        "status": shift.status,
        "driver_name": shift.driver_name,
        "vehicle_reg": shift.vehicle_reg,
        "clocked_in_at": shift.clocked_in_at.isoformat() if shift.clocked_in_at else None,
    }


@router.post("/{shift_id}/photos", dependencies=SHIFTS)
async def upload_photos(
    shift_id: uuid.UUID,
    photo_type: str = Query(..., pattern="^(odometer|fuel|adblue)_(in|out)$"),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Upload a clock-in/out photo as multipart form data (avoids 502 from large JSON bodies)."""
    shift = (await session.execute(
        select(Shift).where(Shift.id == shift_id)
    )).scalar_one_or_none()
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found.")
    meta = _store_upload(file)
    session.add(ShiftPhoto(
        shift_id=shift.id,
        photo_type=photo_type,
        content_type=meta["content_type"],
        storage_path=meta["storage_path"],
    ))
    await session.commit()
    return {"ok": True, "photo_type": photo_type}


# --- Query endpoints (before /{shift_id}) ---

@router.get("/active", dependencies=SHIFTS)
async def active_shifts(session: AsyncSession = Depends(get_session)) -> list[dict]:
    """List all currently active shifts."""
    rows = (await session.execute(
        select(Shift).where(
            Shift.status.in_(["clocked_in", "on_break", "active"])
        ).order_by(Shift.clocked_in_at.desc())
    )).scalars().all()
    return [_shift_summary(s) for s in rows]


@router.get("/history", dependencies=SHIFTS)
async def shift_history(
    limit: int = 100,
    driver_name: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """List completed shifts."""
    stmt = select(Shift).where(Shift.status == "clocked_out")
    if driver_name:
        stmt = stmt.where(Shift.driver_name.ilike(f"%{driver_name}%"))
    rows = (await session.execute(
        stmt.order_by(Shift.clocked_out_at.desc()).limit(min(limit, 500))
    )).scalars().all()
    return [_shift_summary(s) for s in rows]


# --- Job endpoints (before /{shift_id}) ---

@router.post("/jobs", status_code=201, dependencies=JOBS)
async def create_job(body: JobCreateRequest, session: AsyncSession = Depends(get_session),
                     principal: Principal = Depends(require_manager)) -> dict:
    """Owner/admin sends a job to a driver."""
    job = Job(
        driver_name=body.driver_name,
        vehicle_reg=body.vehicle_reg,
        title=body.title,
        description=body.description,
        pickup_location=body.pickup_location,
        dropoff_location=body.dropoff_location,
        priority=body.priority,
        scheduled_at=body.scheduled_at,
        assigned_by=principal.name,
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return _job_summary(job)


@router.get("/jobs", dependencies=JOBS)
async def list_jobs(
    status: str | None = None,
    driver_name: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """List all jobs, optionally filtered by status or driver."""
    stmt = select(Job)
    if status:
        stmt = stmt.where(Job.status == status)
    if driver_name:
        stmt = stmt.where(Job.driver_name.ilike(f"%{driver_name}%"))
    rows = (await session.execute(
        stmt.order_by(Job.created_at.desc()).limit(200)
    )).scalars().all()
    return [_job_summary(j) for j in rows]


@router.get("/jobs/{job_id}", dependencies=JOBS_ANY)
async def get_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                  principal: Principal = Depends(require_driver_or_manager)) -> dict:
    """Get full job details."""
    job = (await session.execute(
        select(Job).where(Job.id == job_id)
    )).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    ensure_own(principal, job.driver_name)
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
async def post_job_message(
    job_id: uuid.UUID, body: JobMessageRequest,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_driver_or_manager),
) -> list[dict]:
    """Driver or office adds to a job's message thread; returns the whole thread."""
    job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    ensure_own(principal, job.driver_name)
    # Sender and author come from the sign-in, not the request body.
    session.add(JobMessage(job_id=job.id, sender="office" if principal.is_manager else "driver",
                           author=principal.name, kind=body.kind, body=body.body.strip()))
    await session.commit()
    return await _job_messages(session, job.id)


@router.post("/jobs/{job_id}/start", dependencies=JOBS_ANY)
async def start_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                    principal: Principal = Depends(require_driver_or_manager)) -> dict:
    """Driver starts an accepted job (Allocated -> Accepted -> In Progress -> Completed)."""
    job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    ensure_own(principal, job.driver_name)
    if job.status != "accepted":
        raise HTTPException(status_code=400, detail=f"Job must be accepted first (currently {job.status}).")
    job.status = "in_progress"
    job.started_at = datetime.now(timezone.utc)
    await session.commit()
    return _job_summary(job)


@router.post("/jobs/{job_id}/accept", dependencies=JOBS_ANY)
async def accept_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                     principal: Principal = Depends(require_driver_or_manager)) -> dict:
    """Driver accepts a job."""
    job = (await session.execute(
        select(Job).where(Job.id == job_id)
    )).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    ensure_own(principal, job.driver_name)
    if job.status != "pending":
        raise HTTPException(status_code=400, detail=f"Job is already {job.status}.")

    job.status = "accepted"
    job.accepted_at = datetime.now(timezone.utc)

    shift = (await session.execute(
        select(Shift).where(
            Shift.driver_name == job.driver_name,
            Shift.status.in_(["clocked_in", "on_break", "active"])
        )
    )).scalar_one_or_none()
    if shift:
        session.add(ShiftJob(shift_id=shift.id, job_id=job.id))

    await session.commit()
    return _job_summary(job)


@router.post("/jobs/{job_id}/deny", dependencies=JOBS_ANY)
async def deny_job(
    job_id: uuid.UUID, body: JobActionRequest,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_driver_or_manager),
) -> dict:
    """Driver denies a job with an optional reason."""
    job = (await session.execute(
        select(Job).where(Job.id == job_id)
    )).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    ensure_own(principal, job.driver_name)
    if job.status != "pending":
        raise HTTPException(status_code=400, detail=f"Job is already {job.status}.")

    job.status = "denied"
    job.denied_at = datetime.now(timezone.utc)
    job.deny_reason = body.reason

    await session.commit()
    return _job_summary(job)


@router.post("/jobs/{job_id}/complete", dependencies=JOBS_ANY)
async def complete_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session),
                       principal: Principal = Depends(require_driver_or_manager)) -> dict:
    """Mark a job as completed."""
    job = (await session.execute(
        select(Job).where(Job.id == job_id)
    )).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    ensure_own(principal, job.driver_name)
    if job.status not in ("accepted", "in_progress"):
        raise HTTPException(status_code=400, detail=f"Job must be accepted first (currently {job.status}).")

    job.status = "completed"
    job.completed_at = datetime.now(timezone.utc)

    await session.commit()
    return _job_summary(job)


@router.post("/jobs/{job_id}/cancel", dependencies=JOBS)
async def cancel_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    """Owner cancels a job."""
    job = (await session.execute(
        select(Job).where(Job.id == job_id)
    )).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Job is already {job.status}.")

    job.status = "cancelled"

    await session.commit()
    return _job_summary(job)


class JobResendRequest(BaseModel):
    driver_name: str | None = Field(default=None, max_length=100)  # None = same driver
    scheduled_at: datetime | None = None


@router.post("/jobs/{job_id}/resend", dependencies=JOBS)
async def resend_job(
    job_id: uuid.UUID, body: JobResendRequest,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_manager),
) -> dict:
    """Send a declined or cancelled job again, to the same or a different driver."""
    job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status not in ("denied", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Only declined or cancelled jobs can be resent (this one is {job.status}).")
    new_driver = " ".join((body.driver_name or "").split()) or job.driver_name
    previous = f"declined by {job.driver_name}" + (f": {job.deny_reason}" if job.deny_reason else "") \
        if job.status == "denied" else "cancelled"
    note = f"Resent to {new_driver} by {principal.name} (previously {previous})."
    job.driver_name = new_driver
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
    """Every driver a job can go to: DH FleetView drivers (as this user sees them),
    driver app accounts, and names already used on jobs/shifts."""
    from app.models.driver_auth import DriverAccount
    from app.services import auth as auth_service

    by_name: dict[str, dict] = {}

    def add(name: str | None, source: str, **extra) -> None:
        name = " ".join((name or "").split())
        if not name:
            return
        entry = by_name.setdefault(name.lower(), {"name": name, "unique_id": None, "in_fleetview": False, "app_access": False})
        if source == "fleetview":
            entry["in_fleetview"] = True
        entry.update({k: v for k, v in extra.items() if v})

    try:
        drivers = await auth_service.traccar_get(principal, "/api/drivers?all=true" if principal.administrator else "/api/drivers")
    except Exception:
        drivers = None
    for d in drivers or []:
        add(d.get("name"), "fleetview", unique_id=d.get("uniqueId"))
    for a in (await session.execute(select(DriverAccount))).scalars().all():
        add(a.name, "account", unique_id=a.unique_id, app_access=bool(a.active))
    for (name,) in (await session.execute(select(Job.driver_name).distinct())).all():
        add(name, "history")
    for (name,) in (await session.execute(select(Shift.driver_name).distinct())).all():
        add(name, "history")
    return sorted(by_name.values(), key=lambda e: e["name"].lower())


# --- Photo endpoint (before /{shift_id}) ---

@router.get("/photos/{photo_id}", dependencies=SHIFTS)
async def get_photo(photo_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Response:
    p = (await session.execute(
        select(ShiftPhoto).where(ShiftPhoto.id == photo_id)
    )).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="Photo not found.")
    try:
        return Response(content=media_store.read(p.storage_path), media_type=p.content_type)
    except OSError:
        raise HTTPException(status_code=404, detail="Photo file missing.")


# --- Parameterised shift endpoints (LAST) ---

@router.get("/{shift_id}", dependencies=SHIFTS)
async def get_shift(shift_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    """Get full shift details including photos and jobs."""
    shift = (await session.execute(
        select(Shift).where(Shift.id == shift_id)
    )).scalar_one_or_none()
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found.")

    photos = (await session.execute(
        select(ShiftPhoto).where(ShiftPhoto.shift_id == shift_id)
    )).scalars().all()

    job_links = (await session.execute(
        select(ShiftJob).where(ShiftJob.shift_id == shift_id)
    )).scalars().all()
    job_ids = [jl.job_id for jl in job_links]
    jobs = []
    if job_ids:
        job_rows = (await session.execute(
            select(Job).where(Job.id.in_(job_ids))
        )).scalars().all()
        jobs = [_job_summary(j) for j in job_rows]

    return {
        **_shift_summary(shift),
        "photos": [{"id": str(p.id), "photo_type": p.photo_type} for p in photos],
        "jobs": jobs,
    }


@router.post("/{shift_id}/clock-out", dependencies=SHIFTS)
async def clock_out(
    shift_id: uuid.UUID, body: ClockOutRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Driver clocks out with end-of-shift readings and photos."""
    shift = (await session.execute(
        select(Shift).where(Shift.id == shift_id)
    )).scalar_one_or_none()
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found.")
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
        session.add(ShiftPhoto(
            shift_id=shift.id,
            photo_type=f"{p.photo_type}_out",
            content_type=meta["content_type"],
            storage_path=meta["storage_path"],
        ))

    await session.commit()
    return {
        "id": str(shift.id),
        "status": shift.status,
        "clocked_out_at": shift.clocked_out_at.isoformat() if shift.clocked_out_at else None,
    }


@router.post("/{shift_id}/break")
async def toggle_break(
    shift_id: uuid.UUID, body: BreakRequest,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_driver_or_manager),
) -> dict:
    """Start or end a break during an active shift."""
    shift = (await session.execute(
        select(Shift).where(Shift.id == shift_id)
    )).scalar_one_or_none()
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found.")
    ensure_own(principal, shift.driver_name)
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

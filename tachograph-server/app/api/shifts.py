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

from app.config import settings
from app.database import get_session
from app.models.shifts import Shift, ShiftPhoto, Job, ShiftJob
from app.services import media_store

router = APIRouter(prefix="/api/shifts", tags=["shifts"])


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


class JobActionRequest(BaseModel):
    reason: str | None = None


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

@router.post("/clock-in", status_code=201)
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


@router.post("/{shift_id}/photos")
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

@router.get("/active")
async def active_shifts(session: AsyncSession = Depends(get_session)) -> list[dict]:
    """List all currently active shifts."""
    rows = (await session.execute(
        select(Shift).where(
            Shift.status.in_(["clocked_in", "on_break", "active"])
        ).order_by(Shift.clocked_in_at.desc())
    )).scalars().all()
    return [_shift_summary(s) for s in rows]


@router.get("/history")
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

@router.post("/jobs", status_code=201)
async def create_job(body: JobCreateRequest, session: AsyncSession = Depends(get_session)) -> dict:
    """Owner/admin sends a job to a driver."""
    job = Job(
        driver_name=body.driver_name,
        vehicle_reg=body.vehicle_reg,
        title=body.title,
        description=body.description,
        pickup_location=body.pickup_location,
        dropoff_location=body.dropoff_location,
        priority=body.priority,
        status="pending",
    )
    session.add(job)
    await session.commit()
    return _job_summary(job)


@router.get("/jobs")
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


@router.get("/jobs/{job_id}")
async def get_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    """Get full job details."""
    job = (await session.execute(
        select(Job).where(Job.id == job_id)
    )).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {
        **_job_summary(job),
        "description": job.description,
        "pickup_location": job.pickup_location,
        "dropoff_location": job.dropoff_location,
        "assigned_by": job.assigned_by,
        "deny_reason": job.deny_reason,
    }


@router.post("/jobs/{job_id}/accept")
async def accept_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    """Driver accepts a job."""
    job = (await session.execute(
        select(Job).where(Job.id == job_id)
    )).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
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


@router.post("/jobs/{job_id}/deny")
async def deny_job(
    job_id: uuid.UUID, body: JobActionRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Driver denies a job with an optional reason."""
    job = (await session.execute(
        select(Job).where(Job.id == job_id)
    )).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != "pending":
        raise HTTPException(status_code=400, detail=f"Job is already {job.status}.")

    job.status = "denied"
    job.denied_at = datetime.now(timezone.utc)
    job.deny_reason = body.reason

    await session.commit()
    return _job_summary(job)


@router.post("/jobs/{job_id}/complete")
async def complete_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    """Mark a job as completed."""
    job = (await session.execute(
        select(Job).where(Job.id == job_id)
    )).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != "accepted":
        raise HTTPException(status_code=400, detail=f"Job must be accepted first (currently {job.status}).")

    job.status = "completed"
    job.completed_at = datetime.now(timezone.utc)

    await session.commit()
    return _job_summary(job)


@router.post("/jobs/{job_id}/cancel")
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


# --- Photo endpoint (before /{shift_id}) ---

@router.get("/photos/{photo_id}")
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

@router.get("/{shift_id}")
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


@router.post("/{shift_id}/clock-out")
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
) -> dict:
    """Start or end a break during an active shift."""
    shift = (await session.execute(
        select(Shift).where(Shift.id == shift_id)
    )).scalar_one_or_none()
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found.")
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
        "driver_name": j.driver_name,
        "vehicle_reg": j.vehicle_reg,
        "title": j.title,
        "priority": j.priority,
        "status": j.status,
        "assigned_at": j.assigned_at.isoformat() if j.assigned_at else None,
        "accepted_at": j.accepted_at.isoformat() if j.accepted_at else None,
        "denied_at": j.denied_at.isoformat() if j.denied_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        "deny_reason": j.deny_reason,
    }

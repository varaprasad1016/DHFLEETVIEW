"""Tacho compliance API: download-window status, .ddd archive/upload, and the
drivers'-hours / WTD infringement engine. Every route is licence-gated.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_license
from app.database import get_session
from app.models.tacho import Infringement, TachoFile
from app.services import archive, ddd_parser, tacho_compliance
from app.services.tacho_rules import Activity, analyse

router = APIRouter(prefix="/api/tacho", tags=["tacho"], dependencies=[Depends(require_license)])


# --- schemas ----------------------------------------------------------------

class ActivityIn(BaseModel):
    type: str = Field(pattern="^(drive|work|available|rest)$")
    start: datetime
    end: datetime


class AnalyzeIn(BaseModel):
    driver_ref: str
    activities: list[ActivityIn]
    source_file_id: uuid.UUID | None = None


class UploadIn(BaseModel):
    filename: str
    content_base64: str
    file_kind: str = Field(default="driver_card", pattern="^(driver_card|vehicle_unit|unknown)$")
    driver_ref: str | None = None
    vehicle_ref: str | None = None


class StatusIn(BaseModel):
    status: str = Field(pattern="^(open|acknowledged|dismissed)$")


# --- helpers ----------------------------------------------------------------

def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _persist_infringements(session: AsyncSession, driver_ref: str, found: list,
                                 source_file_id: uuid.UUID | None) -> int:
    if not found:
        return 0
    keys = [f"{driver_ref}|{i.rule}|{i.start.isoformat()}" for i in found]
    existing = set((await session.execute(
        select(Infringement.dedup_key).where(Infringement.dedup_key.in_(keys))
    )).scalars().all())
    added = 0
    for inf, key in zip(found, keys):
        if key in existing:
            continue
        session.add(Infringement(
            driver_ref=driver_ref, rule=inf.rule, title=inf.title, severity=inf.severity,
            period_start=inf.start, period_end=inf.end, detail=inf.detail,
            limit_minutes=inf.limit_minutes, actual_minutes=inf.actual_minutes,
            source_file_id=source_file_id, dedup_key=key))
        existing.add(key)
        added += 1
    await session.commit()
    return added


# --- endpoints --------------------------------------------------------------

@router.get("/summary")
async def summary(session: AsyncSession = Depends(get_session)) -> dict:
    comp = await tacho_compliance.compliance(session)
    open_inf = (await session.execute(
        select(func.count()).select_from(Infringement).where(Infringement.status == "open")
    )).scalar_one()
    serious = (await session.execute(
        select(func.count()).select_from(Infringement).where(
            Infringement.status == "open", Infringement.severity.in_(("serious", "very_serious")))
    )).scalar_one()
    files = (await session.execute(select(func.count()).select_from(TachoFile))).scalar_one()
    d = comp["summary"]["drivers"]
    v = comp["summary"]["vehicles"]
    return {
        "open_infringements": open_inf,
        "open_serious": serious,
        "archived_files": files,
        "drivers_overdue": d.get("overdue", 0) + d.get("no_data", 0),
        "vehicles_overdue": v.get("overdue", 0) + v.get("no_data", 0),
    }


@router.get("/compliance")
async def compliance(session: AsyncSession = Depends(get_session)) -> dict:
    return await tacho_compliance.compliance(session)


@router.post("/analyze")
async def analyze(body: AnalyzeIn, session: AsyncSession = Depends(get_session)) -> dict:
    acts = [Activity(a.type, _aware(a.start), _aware(a.end)) for a in body.activities]
    found = analyse(acts)
    added = await _persist_infringements(session, body.driver_ref, found, body.source_file_id)
    return {
        "driver_ref": body.driver_ref,
        "activities": len(acts),
        "infringements_found": len(found),
        "infringements_new": added,
        "results": [i.to_dict(body.driver_ref) for i in found],
    }


@router.post("/upload", status_code=201)
async def upload(body: UploadIn, session: AsyncSession = Depends(get_session)) -> dict:
    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="content_base64 is not valid base64.")
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")

    meta = archive.store(body.filename, data)
    tf = TachoFile(
        filename=body.filename, file_kind=body.file_kind,
        driver_ref=body.driver_ref, vehicle_ref=body.vehicle_ref,
        size_bytes=meta["size_bytes"], sha256=meta["sha256"],
        storage_path=meta["storage_path"], source="upload",
        retain_until=meta["retain_until"])
    session.add(tf)
    await session.flush()

    result = {"file_id": str(tf.id), "sha256": meta["sha256"], "size_bytes": meta["size_bytes"],
              "parsed": False, "infringements_found": 0, "infringements_new": 0}

    if body.file_kind == "driver_card":
        try:
            parsed = ddd_parser.parse_driver_card(data)
            tf.parsed = True
            driver_ref = body.driver_ref or f"file:{meta['sha256'][:8]}"
            found = analyse(parsed["activities"])
            added = await _persist_infringements(session, driver_ref, found, tf.id)
            result.update(parsed=True, days=parsed["days"], driver_ref=driver_ref,
                          infringements_found=len(found), infringements_new=added)
        except Exception as e:
            tf.parsed = False
            tf.parse_error = str(e)[:500]
            result["parse_error"] = str(e)
    await session.commit()
    return result


@router.get("/infringements")
async def list_infringements(status: str = "open", driver_ref: str | None = None,
                             session: AsyncSession = Depends(get_session)) -> list[dict]:
    stmt = select(Infringement).order_by(Infringement.period_start.desc())
    if status != "all":
        stmt = stmt.where(Infringement.status == status)
    if driver_ref:
        stmt = stmt.where(Infringement.driver_ref == driver_ref)
    rows = (await session.execute(stmt.limit(1000))).scalars().all()
    return [{
        "id": str(r.id), "driver_ref": r.driver_ref, "rule": r.rule, "title": r.title,
        "severity": r.severity, "status": r.status,
        "period_start": r.period_start.isoformat(), "period_end": r.period_end.isoformat(),
        "detail": r.detail, "limit_minutes": r.limit_minutes, "actual_minutes": r.actual_minutes,
    } for r in rows]


@router.post("/infringements/{inf_id}/status")
async def set_status(inf_id: uuid.UUID, body: StatusIn,
                     session: AsyncSession = Depends(get_session)) -> dict:
    inf = (await session.execute(
        select(Infringement).where(Infringement.id == inf_id))).scalar_one_or_none()
    if inf is None:
        raise HTTPException(status_code=404, detail="Infringement not found.")
    inf.status = body.status
    await session.commit()
    return {"id": str(inf.id), "status": inf.status}


@router.get("/files")
async def list_files(session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.execute(
        select(TachoFile).order_by(TachoFile.created_at.desc()).limit(500))).scalars().all()
    return [{
        "id": str(f.id), "filename": f.filename, "file_kind": f.file_kind,
        "driver_ref": f.driver_ref, "vehicle_ref": f.vehicle_ref,
        "size_bytes": f.size_bytes, "sha256": f.sha256, "parsed": f.parsed,
        "parse_error": f.parse_error,
        "retain_until": f.retain_until.isoformat() if f.retain_until else None,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    } for f in rows]

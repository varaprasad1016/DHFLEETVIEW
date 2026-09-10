"""Tacho compliance API: download-window status, .ddd archive/upload, and the
drivers'-hours / WTD infringement engine. Every route is licence-gated.
"""

from __future__ import annotations

import base64
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_license
from app.config import settings
from app.database import get_session
from app.models.tacho import Infringement, TachoFile
from app.services import archive, ddd_go, ddd_parser, tacho_compliance, tacho_pdf, tacho_report
from app.services.tacho_rules import Activity, Infringement as RuleInfringement, analyse

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


class ReanalyseIn(BaseModel):
    file_id: uuid.UUID | None = None      # one file, or every archived card
    replace_open: bool = True             # drop the previous run's open rows


# --- helpers ----------------------------------------------------------------

def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_driver_card(data: bytes) -> tuple[dict, str]:
    """Parse with the maintained Go reader, falling back only when configured.

    A failed Go parse is not silently hidden when fallback is disabled: the
    caller records the error with the archived file. This makes deployments
    able to enforce Gen2/signature-capable parsing rather than accidentally
    accepting the old screening reader.
    """
    go_error: Exception | None = None
    if ddd_go.available():
        try:
            return ddd_go.parse_driver_card(data), "tachograph-go"
        except Exception as exc:
            go_error = exc
            if not settings.tacho_parser_fallback:
                raise

    try:
        return ddd_parser.parse_driver_card(data), "builtin-gen1"
    except Exception as fallback_error:
        if go_error is not None:
            raise ValueError(
                f"tachograph-go parser failed: {go_error}; "
                f"built-in parser failed: {fallback_error}") from fallback_error
        raise


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
            parsed, parser_name = _parse_driver_card(data)
            tf.parsed = True
            # Prefer what the caller said, then the card holder's own name or
            # card number, and only fall back to the file hash when the card
            # carries no identification of its own.
            driver_ref = (body.driver_ref or parsed.get("driver_ref")
                          or f"file:{meta['sha256'][:8]}")[:40]
            tf.driver_ref = driver_ref
            found = analyse(parsed["activities"], parsed.get("places"),
                            parsed.get("card_gaps"))
            added = await _persist_infringements(session, driver_ref, found, tf.id)
            result.update(parsed=True, parser=parser_name, days=parsed["days"], driver_ref=driver_ref,
                          driver_name=parsed.get("driver_name"),
                          card_number=parsed.get("card_number"),
                          infringements_found=len(found), infringements_new=added)
        except Exception as e:
            tf.parsed = False
            tf.parse_error = str(e)[:500]
            result["parse_error"] = str(e)
    await session.commit()
    return result


@router.post("/reanalyse")
async def reanalyse(body: ReanalyseIn, session: AsyncSession = Depends(get_session)) -> dict:
    """Re-run the rules over already-archived driver cards.

    Infringements are derived data, so when the engine is corrected the stored
    rows are stale and have to be rebuilt from the .ddd files. Rows a manager
    has already acknowledged or dismissed are left alone: those record a human
    decision, so they are reported back for review instead of being rewritten.
    """
    stmt = select(TachoFile).where(TachoFile.file_kind == "driver_card")
    if body.file_id:
        stmt = stmt.where(TachoFile.id == body.file_id)
    files = (await session.execute(stmt)).scalars().all()

    out = {"files": 0, "removed": 0, "found": 0, "added": 0,
           "kept_actioned": 0, "errors": [], "drivers": []}
    for tf in files:
        try:
            data = archive.read(tf.storage_path)
            parsed, parser_name = _parse_driver_card(data)
        except Exception as e:                       # unreadable / not a card
            tf.parse_error = str(e)[:500]
            out["errors"].append({"file_id": str(tf.id), "filename": tf.filename,
                                  "error": str(e)[:200]})
            continue

        driver_ref = (parsed.get("driver_ref") or tf.driver_ref
                      or f"file:{(tf.sha256 or '')[:8]}")[:40]
        tf.driver_ref = driver_ref
        tf.parsed = True
        tf.parse_error = None

        actioned = (await session.execute(
            select(func.count()).select_from(Infringement).where(
                Infringement.source_file_id == tf.id,
                Infringement.status != "open"))).scalar_one()
        if body.replace_open:
            removed = (await session.execute(
                delete(Infringement).where(
                    Infringement.source_file_id == tf.id,
                    Infringement.status == "open"))).rowcount or 0
            out["removed"] += removed
            await session.flush()

        found = analyse(parsed["activities"], parsed.get("places"),
                        parsed.get("card_gaps"))
        added = await _persist_infringements(session, driver_ref, found, tf.id)
        out["files"] += 1
        out["found"] += len(found)
        out["added"] += added
        out["kept_actioned"] += actioned
        out["drivers"].append({"file_id": str(tf.id), "driver_ref": driver_ref,
                               "parser": parser_name, "days": parsed["days"],
                               "infringements": len(found)})
    await session.commit()
    return out


async def _report_for(session: AsyncSession, file_id: uuid.UUID | None,
                      driver_ref: str | None, start: date | None,
                      end: date | None) -> dict:
    """Pick the card file the report is about, then build the report from it."""
    stmt = select(TachoFile).where(TachoFile.file_kind == "driver_card")
    if file_id:
        stmt = stmt.where(TachoFile.id == file_id)
    elif driver_ref:
        stmt = stmt.where(TachoFile.driver_ref == driver_ref)
    files = (await session.execute(
        stmt.order_by(TachoFile.created_at.desc()))).scalars().all()
    if not files:
        raise HTTPException(status_code=404, detail="No driver-card file to report on.")
    if not file_id and not driver_ref and len({f.driver_ref for f in files}) > 1:
        raise HTTPException(
            status_code=400,
            detail="More than one driver is archived; pass driver_ref or file_id.")
    tf = files[0]

    try:
        parsed, _parser_name = _parse_driver_card(archive.read(tf.storage_path))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not read the card file: {e}")

    # Prefer the infringements on record, so anything a manager has already
    # dismissed stays off the driver's report; fall back to analysing the file
    # when it has never been run through the engine.
    rows = (await session.execute(select(Infringement).where(
        Infringement.source_file_id == tf.id,
        Infringement.status != "dismissed"))).scalars().all()
    if rows:
        found = [RuleInfringement(
            rule=r.rule, title=r.title, severity=r.severity,
            start=r.period_start, end=r.period_end, detail=r.detail or "",
            limit_minutes=r.limit_minutes, actual_minutes=r.actual_minutes)
            for r in rows]
    else:
        found = analyse(parsed["activities"], parsed.get("places"),
                        parsed.get("card_gaps"))

    return tacho_report.build_report(
        parsed, found, start=start, end=end,
        driver_ref=tf.driver_ref or parsed.get("driver_ref"))


@router.get("/report")
async def report(file_id: uuid.UUID | None = None, driver_ref: str | None = None,
                 start: date | None = None, end: date | None = None,
                 session: AsyncSession = Depends(get_session)) -> dict:
    return await _report_for(session, file_id, driver_ref, start, end)


@router.get("/report.pdf")
async def report_pdf(file_id: uuid.UUID | None = None, driver_ref: str | None = None,
                     start: date | None = None, end: date | None = None,
                     session: AsyncSession = Depends(get_session)) -> Response:
    data = await _report_for(session, file_id, driver_ref, start, end)
    who = (data["driver"].get("name") or data["driver"].get("ref") or "driver")
    safe = "".join(c if c.isalnum() else "_" for c in who).strip("_") or "driver"
    name = f"{safe}_{data['period']['from']}_{data['period']['to']}.pdf"
    return Response(
        content=tacho_pdf.render(data), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'})


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

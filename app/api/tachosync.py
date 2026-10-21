"""Downloads: what TachoSync holds, and bringing it here.

GET  /api/tachosync/overview        account, vehicles, and why a download failed
GET  /api/tachosync/files           every file TachoSync has, newest first
GET  /api/tachosync/files/{kind}/{file_id}   the file itself, streamed to the browser
POST /api/tachosync/sync            fetch anything new into our archive

The split is deliberate: TachoSync does the download from the vehicle, we keep
the file. Nothing here writes to TachoSync.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_license, require_manager, require_module
from app.database import get_session
from app.models.core import Company
from app.services import tachosync
from app.services.auth import Principal

logger = logging.getLogger("tacho.tachosync")

router = APIRouter(prefix="/api/tachosync", tags=["tachosync"],
                   dependencies=[Depends(require_license), Depends(require_manager),
                                 Depends(require_module("tacho"))])


@router.get("/overview")
async def overview() -> dict:
    """The state of the integration, in the order someone would ask it.

    Is it connected, which vehicles does TachoSync know about, when did each
    last talk to it, and - the question that actually matters when no file has
    arrived - what happened on the last attempt.
    """
    if not tachosync.configured():
        return {"configured": False,
                "hint": "Set TACHOSYNC_API_KEY in the environment to connect the account."}
    try:
        company = await tachosync.company()
        vehicles = await tachosync.vehicles()
    except tachosync.TachoSyncError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    rows = []
    for vehicle in vehicles:
        history = []
        try:
            history = await tachosync.downloads_history(vehicle["id"])
        except tachosync.TachoSyncError:
            pass        # the vehicle still belongs on the list without its history
        last_failure = next((h for h in history if h.get("failedStep")), None)
        rows.append({
            "id": vehicle.get("id"),
            "registration": vehicle.get("number"),
            "imei": vehicle.get("imei"),
            "status": vehicle.get("status"),
            "last_connected": vehicle.get("lastConnected"),
            "last_download": vehicle.get("lastSuccessfulDownloadTime"),
            "credit_status": vehicle.get("creditStatus"),
            "attempts": history[:5],
            "blocked_by": {"stage": last_failure.get("stage"), "detail": last_failure.get("details")}
            if last_failure and not vehicle.get("lastSuccessfulDownloadTime") else None,
        })
    return {"configured": True, "company": company.get("name"), "vehicles": rows}


@router.get("/files")
async def files() -> dict:
    if not tachosync.configured():
        return {"configured": False, "files": []}
    try:
        vehicle_files = await tachosync.vehicle_files()
        driver_files = await tachosync.driver_files()
    except tachosync.TachoSyncError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    def view(entry: dict, kind: str) -> dict:
        return {
            "id": entry.get("id"),
            "kind": kind,
            "name": entry.get("fileName") or entry.get("name"),
            "created_at": entry.get("createdAt"),
            "size": entry.get("fileSize") or entry.get("size"),
            "vehicle": entry.get("vehicleNumber") or entry.get("vehicleImei"),
            "driver": entry.get("driverName") or entry.get("driverCardNumber"),
            "format": entry.get("fileFormat"),
        }

    rows = [view(f, "vehicle") for f in vehicle_files] + [view(f, "driver") for f in driver_files]
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return {"configured": True, "files": rows}


@router.get("/files/{kind}/{file_id}")
async def file_content(kind: str, file_id: str) -> Response:
    if kind not in ("vehicle", "driver"):
        raise HTTPException(status_code=404, detail="Unknown file kind.")
    try:
        content, content_type = await tachosync.download(kind, [file_id])
    except tachosync.TachoSyncError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    suffix = "zip" if "zip" in content_type else "ddd"
    return Response(content, media_type=content_type, headers={
        "Content-Disposition": f'attachment; filename="{kind}-{file_id}.{suffix}"'})


@router.post("/sync")
async def sync(days: int = 30) -> dict:
    """Fetch anything new into our archive. Safe to repeat: files already on
    record are skipped."""
    return await tachosync.sync(days=days)


@router.get("/keys")
async def list_keys(session: AsyncSession = Depends(get_session),
                    principal: Principal = Depends(require_manager)) -> dict:
    """Which customers have their own TachoSync key, and how their last fetch went.

    The key itself is never sent back. Showing it would put a working
    credential on a screen and in the browser's cache for no benefit: it is
    needed to be set, not to be read.
    """
    rows = (await session.execute(
        select(Company).where(Company.active.is_(True)).order_by(Company.name))).scalars().all()
    return {"customers": [{
        "id": str(c.id),
        "name": c.name,
        "has_key": bool((c.tachosync_api_key or "").strip()),
        "checked_at": c.tachosync_checked_at.isoformat() if c.tachosync_checked_at else None,
        "status": c.tachosync_status,
    } for c in rows]}


@router.put("/keys/{company_id}")
async def set_key(company_id: uuid.UUID, body: dict = Body(...),
                  session: AsyncSession = Depends(get_session),
                  principal: Principal = Depends(require_manager)) -> dict:
    """Give a customer their own TachoSync key, or take it away.

    The key is checked against TachoSync before it is saved: a key that is
    stored but wrong means a customer whose files quietly never arrive, which
    nobody notices until somebody asks for a download that was never fetched.
    """
    company = await session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="That customer is not on record.")

    key = (body.get("api_key") or "").strip()
    if not key:
        company.tachosync_api_key = None
        company.tachosync_status = "no key"
        company.tachosync_checked_at = datetime.now(timezone.utc)
        await session.commit()
        return {"saved": True, "has_key": False, "status": company.tachosync_status}

    try:
        account = await tachosync.company(key=key)
    except tachosync.TachoSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    name = None
    if isinstance(account, dict):
        name = account.get("name") or (account.get("items") or [{}])[0].get("name")
    company.tachosync_api_key = key
    company.tachosync_checked_at = datetime.now(timezone.utc)
    company.tachosync_status = f"connected to {name}" if name else "connected"
    await session.commit()
    return {"saved": True, "has_key": True, "status": company.tachosync_status,
            "tachosync_company": name}

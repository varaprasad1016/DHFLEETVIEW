"""DVR setup by text message.

A camera has to be told where the server is before it will ever connect, and
that is done by SMS to the SIM in the DVR (the "Mobile No." on its label). The
commands are kept here so they can be sent from the platform, in order, and seen
again later.

Office (super administrator):
POST   /api/dvr/labels              read a photo of a DVR label
GET    /api/dvr/labels/{id}         the photo again, for the review screen
POST   /api/dvr/vehicles            create the vehicle from a confirmed label
GET    /api/dvr/commands            the saved commands
PUT    /api/dvr/commands            replace the saved commands
POST   /api/dvr/send                queue commands for one vehicle
GET    /api/dvr/messages            what was sent, and how it went

The sending phone (a spare Android handset with a SIM, authenticated by a key):
GET    /api/dvr/outbox              claim queued messages to send
POST   /api/dvr/outbox/{id}         report each one sent or failed
"""

from __future__ import annotations

import asyncio
import logging
import urllib.error
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_manager
from app.config import settings
from app.database import get_session
from app.models.dvr import DvrCommand, DvrMessage
from app.services import auth, cnms_db, dvr_labels, modules
from app.services.auth import Principal

logger = logging.getLogger("tacho.dvr")

router = APIRouter(prefix="/api/dvr", tags=["dvr"])

# What a new DVR is normally told: which protocol to speak, where to report, and
# two status questions to confirm it worked.
DEFAULT_COMMANDS = [
    ("Set protocol", "*admin,111111,SETPROTOCOL:protocol1=3,protocol2=4"),
    ("Set server 1", "*admin,111111,SETNIP:1,109.228.53.195:9808;"),
    ("Set server 2", "*admin,111111,SETNIP:2,139.159.218.255:6608;"),
    ("Check 4G", "*GETSTATE4G"),
    ("Check base", "*GETSTATEBASE"),
]
CLAIM_TIMEOUT = timedelta(minutes=5)
# Longer than any healthy sender's round trip: past this, nothing is collecting.
STALE_AFTER = timedelta(minutes=10)


def now() -> datetime:
    return datetime.now(timezone.utc)


def _require_super(principal: Principal) -> None:
    if not modules.is_super_admin(principal):
        raise HTTPException(status_code=403, detail="Only a super administrator can send DVR setup commands.")


async def _commands(session: AsyncSession) -> list[DvrCommand]:
    rows = (await session.execute(select(DvrCommand).order_by(DvrCommand.position, DvrCommand.name))).scalars().all()
    if rows:
        return rows
    # First use: start from the commands that bring one of these cameras online.
    rows = [DvrCommand(name=name, body=body, position=index, enabled=True)
            for index, (name, body) in enumerate(DEFAULT_COMMANDS)]
    session.add_all(rows)
    await session.commit()
    return rows


def _view(command: DvrCommand) -> dict:
    return {"id": str(command.id), "name": command.name, "body": command.body,
            "position": command.position, "enabled": command.enabled}


# ------------------------------------------------------------------ labels
def _label_dir() -> Path:
    path = Path(settings.dvr_label_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


@router.post("/labels")
async def read_label(photo: UploadFile = File(...), principal: Principal = Depends(require_manager)):
    """What a photo of a DVR label says: the numbers come from its barcodes.

    The registration and the customer are handwritten on these labels, so they
    are left for the operator to confirm against the photo.
    """
    _require_super(principal)
    data = await photo.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="That photo is too large. 15 MB is the limit.")
    # Barcodes and OCR both take a moment; keep the server answering meanwhile.
    fields = await asyncio.to_thread(dvr_labels.read_label, data)

    identifier = uuid.uuid4().hex
    (_label_dir() / f"{identifier}.jpg").write_bytes(data)
    fields["photo_id"] = identifier
    fields["photo_url"] = f"/tacho/api/dvr/labels/{identifier}"

    # Say straight away if this camera is already known on either side.
    device_id = fields.get("device_id")
    if device_id:
        existing = await auth.traccar_get(principal, "/api/devices") or []
        match = next((d for d in existing if (d.get("attributes") or {}).get("cmsv9DeviceId") == device_id), None)
        fields["already_here"] = {"id": match["id"], "name": match["name"]} if match else None
        try:
            fields["already_in_cnms"] = cnms_db.find_device(device_id)
        except Exception:  # noqa: BLE001 - CNMS being unreachable must not stop the read
            fields["already_in_cnms"] = None
    return fields


@router.get("/labels/{photo_id}")
async def label_photo(photo_id: str, principal: Principal = Depends(require_manager)):
    _require_super(principal)
    if not photo_id.isalnum():
        raise HTTPException(status_code=404)
    path = _label_dir() / f"{photo_id}.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/jpeg")


@router.get("/cnms/companies")
async def cnms_companies(principal: Principal = Depends(require_manager)):
    """The CNMS companies a camera can be created under, and how full each is."""
    _require_super(principal)
    try:
        return {"companies": cnms_db.companies(), "default": settings.cnms_default_company, "available": True}
    except Exception as exc:  # noqa: BLE001
        return {"companies": [], "default": settings.cnms_default_company, "available": False, "detail": str(exc)}


@router.post("/vehicles")
async def create_vehicle(body: dict = Body(...), principal: Principal = Depends(require_manager)):
    """Create the vehicle from a confirmed label: here first, then CNMS."""
    _require_super(principal)
    registration = str(body.get("registration") or "").strip().upper()
    device_id = str(body.get("device_id") or "").strip()
    sim_no = str(body.get("sim_no") or "").strip()
    mobile_no = str(body.get("mobile_no") or "").strip().replace(" ", "")
    serial = str(body.get("serial") or "").strip()
    account_id = body.get("account_user_id")

    if not registration or not device_id:
        raise HTTPException(status_code=400, detail="A registration and a device ID are needed.")

    existing = await auth.traccar_get(principal, "/api/devices") or []
    if any((d.get("attributes") or {}).get("cmsv9DeviceId") == device_id for d in existing):
        raise HTTPException(status_code=409, detail=f"Device {device_id} is already on DH FleetView.")

    device = {
        "name": registration,
        "uniqueId": f"cnms-{device_id}",
        "category": "CNMS",
        "phone": mobile_no,
        "attributes": {k: v for k, v in {
            "cmsv9DeviceId": device_id,
            "cmsv9Name": registration,
            "cmsv9Mobile": mobile_no,
            "cmsv9Sim": sim_no,
            "cmsv9Serial": serial,
            "labelPhoto": body.get("photo_id"),
        }.items() if v},
    }
    try:
        created = await auth.traccar_send(principal, "POST", "/api/devices", device)
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"DH FleetView refused the vehicle: {exc.read().decode()[:200]}") from exc

    result = {"device": {"id": created.get("id"), "name": created.get("name")}, "cnms": None, "account": None}

    if account_id:
        try:
            await auth.traccar_send(principal, "POST", "/api/permissions",
                                    {"userId": int(account_id), "deviceId": created["id"]})
            result["account"] = int(account_id)
        except Exception:  # noqa: BLE001 - the vehicle exists; the sharing can be fixed by hand
            result["account_error"] = "The vehicle was created but could not be given to that account."

    # Then CNMS, so the camera's video works as well as its position. A camera
    # already there is left exactly as it is.
    try:
        result["cnms_existing"] = cnms_db.find_device(device_id)
    except Exception:  # noqa: BLE001 - CNMS being unreachable must not undo the vehicle
        result["cnms_existing"] = None
        result["cnms_error"] = "CNMS could not be reached, so the camera was not added there."
        return result

    if result["cnms_existing"] is None:
        try:
            result["cnms"] = cnms_db.create_vehicle(
                device_id=device_id, registration=registration, sim_no=sim_no,
                company=str(body.get("cnms_company") or "").strip(),
                channels=int(body.get("channels") or 4))
        except Exception as exc:  # noqa: BLE001 - the vehicle here stands either way
            logger.exception("could not add %s to CNMS", device_id)
            result["cnms_error"] = str(exc)
    return result


@router.get("/commands")
async def list_commands(principal: Principal = Depends(require_manager), session: AsyncSession = Depends(get_session)):
    _require_super(principal)
    return {"commands": [_view(c) for c in await _commands(session)],
            "gateway_number": settings.dvr_sms_from or None}


@router.put("/commands")
async def save_commands(body: dict = Body(...), principal: Principal = Depends(require_manager),
                        session: AsyncSession = Depends(get_session)):
    """Replace the saved list, keeping the order given."""
    _require_super(principal)
    incoming = body.get("commands")
    if not isinstance(incoming, list):
        raise HTTPException(status_code=400, detail="Send the commands to save.")
    existing = {str(c.id): c for c in (await session.execute(select(DvrCommand))).scalars().all()}
    kept: set[str] = set()
    for position, item in enumerate(incoming):
        name = str(item.get("name") or "").strip()[:80]
        text = str(item.get("body") or "").strip()
        if not name or not text:
            continue
        command = existing.get(str(item.get("id")))
        if command is None:
            command = DvrCommand(name=name, body=text)
            session.add(command)
        command.name, command.body = name, text
        command.position = position
        command.enabled = bool(item.get("enabled", True))
        command.updated_by = principal.email or principal.name
        command.updated_at = now()
        kept.add(str(item.get("id")))
    for command_id, command in existing.items():
        if command_id not in kept:
            await session.delete(command)
    await session.commit()
    return {"commands": [_view(c) for c in await _commands(session)]}


@router.post("/send")
async def send_commands(body: dict = Body(...), principal: Principal = Depends(require_manager),
                        session: AsyncSession = Depends(get_session)):
    """Queue the chosen commands for one vehicle's DVR SIM."""
    _require_super(principal)
    device_id = body.get("device_id")
    number = str(body.get("to_number") or "").strip()
    device_name = None

    if device_id is not None:
        device = await auth.traccar_get(principal, f"/api/devices/{device_id}")
        if not device:
            raise HTTPException(status_code=404, detail="That vehicle isn't one you can see.")
        device_name = device.get("name")
        attributes = device.get("attributes") or {}
        number = number or str(attributes.get("cmsv9Mobile") or attributes.get("phone") or device.get("phone") or "")

    number = number.replace(" ", "")
    if not number:
        raise HTTPException(status_code=400, detail="No mobile number for this DVR. Add the number from its label first.")

    chosen = body.get("command_ids")
    commands = [c for c in await _commands(session) if c.enabled]
    if isinstance(chosen, list) and chosen:
        wanted = {str(c) for c in chosen}
        commands = [c for c in commands if str(c.id) in wanted]
    if not commands:
        raise HTTPException(status_code=400, detail="Choose at least one command to send.")

    queued = []
    for command in commands:
        message = DvrMessage(to_number=number, body=command.body, device_id=device_id, device_name=device_name,
                             command_name=command.name, queued_by=principal.email or principal.name)
        session.add(message)
        queued.append(message)
    await session.commit()
    return {"queued": [{"id": str(m.id), "command": m.command_name, "to": m.to_number} for m in queued],
            "to_number": number}


@router.get("/messages")
async def list_messages(limit: int = Query(50, ge=1, le=200), principal: Principal = Depends(require_manager),
                        session: AsyncSession = Depends(get_session)):
    _require_super(principal)
    rows = (await session.execute(
        select(DvrMessage).order_by(DvrMessage.queued_at.desc()).limit(limit))).scalars().all()

    # Queueing is not sending. Nothing leaves here until something collects it,
    # so say plainly how long the oldest message has been waiting - otherwise a
    # full queue and a working one look exactly alike.
    waiting = (await session.execute(
        select(DvrMessage.queued_at).where(DvrMessage.status.in_(("queued", "sending")))
        .order_by(DvrMessage.queued_at).limit(1))).scalars().first()
    stale = bool(waiting and now() - waiting > STALE_AFTER)

    return {"messages": [{
        "id": str(m.id), "to": m.to_number, "body": m.body, "device": m.device_name,
        "command": m.command_name, "status": m.status, "detail": m.detail,
        "queued_at": m.queued_at.isoformat() if m.queued_at else None,
        "sent_at": m.sent_at.isoformat() if m.sent_at else None,
    } for m in rows],
        "waiting_since": waiting.isoformat() if waiting else None,
        "nothing_is_collecting": stale}


# ------------------------------------------------------------------ the sending phone
def _check_gateway(key: str | None) -> None:
    """The phone signs in with a key, not a user session: it has no login and the
    queue is the only thing it may touch."""
    expected = settings.dvr_sms_key
    if not expected or key != expected:
        raise HTTPException(status_code=401, detail="Bad or missing gateway key.")


@router.get("/outbox")
async def claim_outbox(limit: int = Query(5, ge=1, le=20), x_gateway_key: str | None = Header(default=None),
                       session: AsyncSession = Depends(get_session)):
    """Messages for the phone to send. Claimed ones are handed out again if the
    phone never reports back, so nothing is lost when it drops off the network."""
    _check_gateway(x_gateway_key)
    stale = now() - CLAIM_TIMEOUT
    rows = (await session.execute(
        select(DvrMessage)
        .where(DvrMessage.status == "queued")
        .order_by(DvrMessage.queued_at)
        .limit(limit))).scalars().all()
    retries = (await session.execute(
        select(DvrMessage)
        .where(DvrMessage.status == "sending", DvrMessage.claimed_at < stale)
        .order_by(DvrMessage.queued_at)
        .limit(limit))).scalars().all()
    for message in [*rows, *retries][:limit]:
        message.status = "sending"
        message.claimed_at = now()
    await session.commit()
    return {"messages": [{"id": str(m.id), "to": m.to_number, "body": m.body}
                         for m in [*rows, *retries][:limit]]}


@router.post("/outbox/{message_id}")
async def report_outbox(message_id: str, body: dict = Body(default={}),
                        x_gateway_key: str | None = Header(default=None),
                        session: AsyncSession = Depends(get_session)):
    _check_gateway(x_gateway_key)
    try:
        identifier = uuid.UUID(message_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="No such message.") from exc
    message = await session.get(DvrMessage, identifier)
    if message is None:
        raise HTTPException(status_code=404, detail="No such message.")
    sent = bool(body.get("sent", True))
    message.status = "sent" if sent else "failed"
    message.detail = str(body.get("detail") or "")[:500] or None
    message.sent_at = now()
    await session.commit()
    return {"id": message_id, "status": message.status}

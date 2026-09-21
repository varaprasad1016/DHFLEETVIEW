"""DVR setup by text message.

A camera has to be told where the server is before it will ever connect, and
that is done by SMS to the SIM in the DVR (the "Mobile No." on its label). The
commands are kept here so they can be sent from the platform, in order, and seen
again later.

Office (super administrator):
GET    /api/dvr/commands            the saved commands
PUT    /api/dvr/commands            replace the saved commands
POST   /api/dvr/send                queue commands for one vehicle
GET    /api/dvr/messages            what was sent, and how it went

The sending phone (a spare Android handset with a SIM, authenticated by a key):
GET    /api/dvr/outbox              claim queued messages to send
POST   /api/dvr/outbox/{id}         report each one sent or failed
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_manager
from app.config import settings
from app.database import get_session
from app.models.dvr import DvrCommand, DvrMessage
from app.services import auth, modules
from app.services.auth import Principal

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
    return {"messages": [{
        "id": str(m.id), "to": m.to_number, "body": m.body, "device": m.device_name,
        "command": m.command_name, "status": m.status, "detail": m.detail,
        "queued_at": m.queued_at.isoformat() if m.queued_at else None,
        "sent_at": m.sent_at.isoformat() if m.sent_at else None,
    } for m in rows]}


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

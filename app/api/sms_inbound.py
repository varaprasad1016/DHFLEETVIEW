"""What Caburn post back to us: camera replies and delivery receipts.

Once commands go out through the SIM portal rather than a handset, a camera's
reply goes to Caburn, not to anyone's phone. They post it here as it arrives.

This endpoint has no session behind it - Caburn have no login - so it is
protected by a passphrase agreed with them, and it accepts nothing else.

POST /tacho/sms/inbound     Caburn's post service delivers here
GET  /api/sms/inbound       what came back, for the office screen
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import String, cast, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_manager
from app.config import settings
from app.database import get_session
from app.models.dvr import DvrMessage
from app.models.sms_inbound import SmsInbound
from app.services import modules
from app.services.auth import Principal

logger = logging.getLogger("tacho.sms")

public_router = APIRouter(prefix="/sms", tags=["sms"])
router = APIRouter(prefix="/api/sms", tags=["sms"])

MAX_POST = 64 * 1024


def _tag(body: str, name: str) -> str | None:
    found = re.search(rf"<{name}>\s*(.*?)\s*</{name}>", body, re.I | re.S)
    return found.group(1) if found else None


def _attr(body: str, name: str) -> str | None:
    found = re.search(rf'{name}\s*=\s*"([^"]*)"', body, re.I)
    return found.group(1) if found else None


def _when(value: str | None) -> datetime | None:
    """Their timestamps are DD/MM/YYYY HH:MM:SS, in UTC."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        logger.warning("could not read a timestamp from the SIM portal: %r", value)
        return None


def _unescape(value: str | None) -> str | None:
    if value is None:
        return None
    for entity, character in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                              ("&#39;", "'"), ("&amp;", "&")):
        value = value.replace(entity, character)
    return value


@public_router.post("/inbound")
async def inbound(request: Request, session: AsyncSession = Depends(get_session)) -> Response:
    """Take one posted reply or receipt.

    Answers 200 to anything it has understood and stored - including something
    it has already seen, because their retry schedule keeps redelivering until
    it gets a 200, and a duplicate is not a failure.
    """
    raw = (await request.body())[:MAX_POST].decode("utf-8", errors="replace")

    if settings.sms_post_passphrase:
        if _tag(raw, "passphrase") != settings.sms_post_passphrase:
            logger.warning("a post to the SMS inbound endpoint had the wrong passphrase")
            raise HTTPException(status_code=401, detail="Bad passphrase.")

    if "<post-sms" in raw:
        kind, delivery_id = "reply", _attr(raw, "api-did")
    elif "<post-delivery-receipt" in raw:
        kind, delivery_id = "receipt", _attr(raw, "api-did")
    else:
        raise HTTPException(status_code=400, detail="Not a message this endpoint understands.")

    if not delivery_id:
        raise HTTPException(status_code=400, detail="No delivery id on that message.")

    item = SmsInbound(
        delivery_id=delivery_id, kind=kind,
        iccid=_tag(raw, "iccid"), msisdn=_tag(raw, "msisdn"),
        body=_unescape(_tag(raw, "message-text")),
        sms_uid=_tag(raw, "sms-uid"), status=_tag(raw, "status"),
        happened_at=_when(_tag(raw, "timestamp") or _tag(raw, "delivered-timestamp")),
        raw=raw[:8000])
    session.add(item)
    try:
        await session.commit()
    except IntegrityError:
        # Already had this one. Their schedule retries until we answer 200.
        await session.rollback()
        logger.info("the SIM portal redelivered %s; ignored", delivery_id)
        return Response(status_code=200)

    # A receipt says what became of a command we sent. We put the message's own
    # id on it as the sms-uid, so it leads straight back to that message.
    if kind == "receipt" and item.sms_uid:
        message = (await session.execute(
            select(DvrMessage).where(
                func.replace(cast(DvrMessage.id, String), "-", "").like(f"{item.sms_uid}%")
            ).limit(1))).scalars().first()
        if message:
            when = f" at {item.happened_at:%d %b %H:%M}" if item.happened_at else ""
            message.detail = f"{item.status or 'reported'}{when}"
            # Their wording for a success is "Delivered"; anything else is not.
            if (item.status or "").lower() != "delivered":
                message.status = "failed"
            await session.commit()
        else:
            logger.info("a receipt arrived for %s, which is not a message we sent", item.sms_uid)

    logger.info("the SIM portal posted a %s from %s", kind, item.msisdn or item.iccid)
    return Response(status_code=200)


@router.get("/inbound")
async def list_inbound(limit: int = Query(100, ge=1, le=500),
                       msisdn: str | None = None,
                       principal: Principal = Depends(require_manager),
                       session: AsyncSession = Depends(get_session)):
    """Replies and receipts, newest first."""
    if not modules.is_super_admin(principal):
        raise HTTPException(status_code=403, detail="Only a super administrator can see this.")
    query = select(SmsInbound).order_by(SmsInbound.received_at.desc()).limit(limit)
    if msisdn:
        query = query.where(SmsInbound.msisdn.in_([msisdn, _international(msisdn)]))
    rows = (await session.execute(query)).scalars().all()
    return {"inbound": [{
        "id": str(row.id), "kind": row.kind, "iccid": row.iccid, "msisdn": row.msisdn,
        "body": row.body, "status": row.status, "sms_uid": row.sms_uid,
        "happened_at": row.happened_at.isoformat() if row.happened_at else None,
        "received_at": row.received_at.isoformat() if row.received_at else None,
    } for row in rows],
        "endpoint": f"{settings.bridge_public_url or ''}/tacho/sms/inbound",
        "passphrase_set": bool(settings.sms_post_passphrase)}


def _international(number: str) -> str:
    digits = re.sub(r"\D", "", number or "")
    return "44" + digits[1:] if digits.startswith("07") else digits

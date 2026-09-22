"""Sending the queued camera setup commands through an SMS provider.

The commands are queued by the office screen and have to reach the SIM inside a
DVR. Anything can do the sending - originally a spare Android handset polling
/api/dvr/outbox, now the SIM provider's own portal, which can text its own SIMs
directly. The queue does not care which, so this drains the same rows the phone
would have claimed.

The provider is described in settings rather than in code, because every
provider's send call is the same shape - a URL, a way of proving who you are,
and a body carrying the number and the text - and differs only in the details.
That means a new provider is four lines of .env rather than a new module:

    SMS_URL=https://portal.example.com/api/v1/sms
    SMS_AUTH_HEADER=Authorization
    SMS_AUTH_VALUE=Bearer <the key>
    SMS_BODY_TEMPLATE={"msisdn": "{to}", "message": "{text}"}

Nothing runs at all unless SMS_URL is set, so a server without it keeps the
old behaviour and waits for something to collect the queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models.dvr import DvrMessage

logger = logging.getLogger("tacho.sms")

POLL_INTERVAL = 20          # seconds between looks at the queue
BATCH = 5                   # messages per pass, so one bad run cannot flood
STUCK_AFTER = timedelta(minutes=5)   # a claim nobody finished is offered again


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SmsError(Exception):
    """The provider would not send this message."""


def _fill(template: str, to: str, text: str) -> str:
    """Put the number and the message into the provider's body template.

    The text is escaped for the format the body is in, so a command containing
    a quote or a backslash cannot break the request - these commands are full
    of punctuation.
    """
    if template.lstrip().startswith(("{", "[")):
        return template.replace("{to}", json.dumps(to)[1:-1]).replace("{text}", json.dumps(text)[1:-1])
    return template.replace("{to}", to).replace("{text}", text)


async def send_one(client: httpx.AsyncClient, to: str, text: str) -> str:
    """Hand one message to the provider. Returns whatever it called the message."""
    if not settings.sms_url:
        raise SmsError("No SMS provider is configured on this server.")

    headers = {"Content-Type": settings.sms_content_type}
    if settings.sms_auth_header and settings.sms_auth_value:
        headers[settings.sms_auth_header] = settings.sms_auth_value
    body = _fill(settings.sms_body_template, to, text)

    try:
        response = await client.request(settings.sms_method, settings.sms_url,
                                        headers=headers, content=body.encode("utf-8"),
                                        timeout=30)
    except httpx.HTTPError as exc:
        raise SmsError(f"The SMS provider could not be reached: {exc}") from exc

    if response.status_code >= 300:
        # Keep the provider's own words: "SIM not active" is the whole answer.
        raise SmsError(f"The SMS provider refused it ({response.status_code}): "
                       f"{response.text.strip()[:200]}")
    return response.text.strip()[:200] or f"sent ({response.status_code})"


async def _drain_once(client: httpx.AsyncClient) -> int:
    """Send what is waiting. Returns how many were dealt with."""
    async with SessionLocal() as session:
        stuck = _now() - STUCK_AFTER
        waiting = (await session.execute(
            select(DvrMessage)
            .where(DvrMessage.status == "queued")
            .order_by(DvrMessage.queued_at).limit(BATCH))).scalars().all()
        retries = (await session.execute(
            select(DvrMessage)
            .where(DvrMessage.status == "sending", DvrMessage.claimed_at < stuck)
            .order_by(DvrMessage.queued_at).limit(BATCH))).scalars().all()
        messages = [*waiting, *retries][:BATCH]
        for message in messages:
            message.status = "sending"
            message.claimed_at = _now()
        await session.commit()

        for message in messages:
            try:
                reference = await send_one(client, message.to_number, message.body)
                message.status, message.detail = "sent", reference
                logger.info("sent %s to %s", message.command_name, message.to_number)
            except SmsError as exc:
                message.status, message.detail = "failed", str(exc)[:500]
                logger.warning("could not send %s to %s: %s",
                               message.command_name, message.to_number, exc)
            message.sent_at = _now()
        await session.commit()
        return len(messages)


async def run() -> None:
    """Watch the queue for as long as the server is up."""
    logger.info("SMS sending is on, through %s", settings.sms_url)
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await _drain_once(client)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a bad pass must not end the loop
                logger.exception("the SMS queue could not be read")
            await asyncio.sleep(POLL_INTERVAL)

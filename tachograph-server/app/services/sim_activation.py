"""Turning SIMs on and off, and knowing whether it actually happened.

Activation is the one SIM operation with a bill and a dark camera behind it, so
nothing here trusts a success response on its own. Two things make that
necessary.

The first is Caburn's API answering HTTP 200 whatever happens, with the real
outcome inside the body - already handled in `caburn.py`, but worth repeating
because it sets the tone.

The second is their staged rollout. Until an account is moved to the live
endpoint, requests are accepted and acknowledged but *not actioned*. A module
that reported "activated" on the strength of the reply would be confidently
wrong, and nobody would find out until a vehicle went dark. So every change is
followed by reading the status back, and a SIM is only reported as activated
when the network itself says it is.

Where the two disagree the answer is "asked, not confirmed" - which is the
honest description of what happened, and the one that gets somebody to look.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.sim import SimCard
from app.services import caburn

logger = logging.getLogger("tacho.sims")

# How many SIMs to talk to the portal about at once.
AT_ONCE = 6

# Outcomes, in the words used on screen.
DONE = "done"                   # the network confirms the new state
UNCONFIRMED = "not_confirmed"   # accepted, but the network still says otherwise
FAILED = "failed"               # the portal refused it outright


def endpoint_is_test() -> bool:
    """Whether the configured portal is Caburn's test endpoint.

    Their staged rollout accepts requests on this URL and acknowledges them
    without carrying them out, so an activation here changes nothing on the
    network however cheerful the reply.
    """
    url = (settings.sms_url or "").lower()
    return "test_api" in url or url.rstrip("/").endswith("/test")


def endpoint_warning() -> str | None:
    """What to tell somebody before they press the button, or None if live."""
    if not caburn.configured():
        return "The SIM portal is not set up on this server yet."
    if endpoint_is_test():
        return ("This server is pointed at Caburn's test endpoint, which accepts "
                "requests without carrying them out. Activations will be reported "
                "as asked but not confirmed, and no SIM will actually change. Ask "
                "Caburn to move the account to the live endpoint.")
    return None


def _is_active(status: str | None) -> bool:
    return (status or "").strip().lower().startswith("active")


async def apply(client: httpx.AsyncClient, iccid: str, *, active: bool) -> dict:
    """Ask for one SIM to change, then read back what the network says.

    The read-back is the whole point: it is what separates "we sent a request"
    from "the SIM is on".
    """
    wanted = "active" if active else "de-activated"
    try:
        before = await caburn.status(client, iccid=iccid)
    except caburn.CaburnError as exc:
        # Not fatal: a SIM the portal will not discuss beforehand may still
        # take the change, and the read-back afterwards is what decides.
        logger.info("could not read SIM %s before changing it: %s", iccid, exc)
        before = None

    try:
        await caburn.set_status(client, active=active, iccid=iccid)
    except caburn.CaburnError as exc:
        return {"iccid": iccid, "wanted": wanted, "outcome": FAILED,
                "was": before, "now": before, "detail": str(exc)}

    try:
        now = await caburn.status(client, iccid=iccid)
    except caburn.CaburnError as exc:
        return {"iccid": iccid, "wanted": wanted, "outcome": UNCONFIRMED,
                "was": before, "now": None,
                "detail": f"the change was accepted but the status could not be "
                          f"read back: {exc}"}

    if _is_active(now) == active:
        return {"iccid": iccid, "wanted": wanted, "outcome": DONE,
                "was": before, "now": now,
                "detail": (f"already {now.lower()}" if before is not None
                           and _is_active(before) == active else None)}

    return {"iccid": iccid, "wanted": wanted, "outcome": UNCONFIRMED,
            "was": before, "now": now,
            "detail": (endpoint_warning() or
                       f"the portal accepted the request but the SIM still reads "
                       f"as {now}. Give it a minute and check again.")}


async def run(session: AsyncSession, iccids: list[str], *, active: bool,
              who: str | None = None) -> dict:
    """Change a batch of SIMs, answering per SIM and recording what happened.

    One SIM the portal will not act on must not hide the fifteen it did, so
    every SIM gets its own answer and nothing is rolled back.
    """
    if not caburn.configured():
        raise caburn.CaburnError("The SIM portal is not set up on this server yet.")
    wanted = [str(i).strip() for i in iccids if str(i).strip()]
    if not wanted:
        raise caburn.CaburnError("No SIMs were given to change.")

    gate = asyncio.Semaphore(AT_ONCE)

    async def one(client, iccid):
        async with gate:
            return await apply(client, iccid, active=active)

    async with httpx.AsyncClient() as client:
        answers = list(await asyncio.gather(*(one(client, i) for i in wanted)))

    # Write back what the network said, so the list screen stops guessing.
    rows = {c.iccid: c for c in (await session.execute(
        select(SimCard).where(SimCard.iccid.in_(wanted)))).scalars().all()}
    now = datetime.now(timezone.utc)
    for answer in answers:
        card = rows.get(answer["iccid"])
        if card is None:
            answer["known"] = False
            continue
        answer["known"] = True
        answer["vehicle"] = card.vehicle
        if answer["now"]:
            card.live_status = answer["now"]
            card.checked_at = now
        if answer["outcome"] == DONE and active:
            card.activated_at = card.activated_at or now
            card.activated_by = who or card.activated_by
    await session.commit()

    done = [a for a in answers if a["outcome"] == DONE]
    logger.info("%s set %d of %d SIM(s) %s", who or "someone", len(done), len(answers),
                "active" if active else "de-activated")
    return {
        "active": active,
        "sims": answers,
        "done": len(done),
        "not_confirmed": sum(1 for a in answers if a["outcome"] == UNCONFIRMED),
        "failed": sum(1 for a in answers if a["outcome"] == FAILED),
        "warning": endpoint_warning(),
    }

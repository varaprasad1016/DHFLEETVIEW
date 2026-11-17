"""Licence API: pair a phone once, then approve each month from that phone —
no server login required.

Endpoints (all under /api/license):
* GET  /status   -> public state the phone app renders (paired? licensed? current period)
* POST /pair     -> one-time trust-on-first-use registration of the phone's public key, gated by the pairing PIN
* POST /approve  -> monthly approval: the phone posts a signed message for the current cycle
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models.licensing import LicenseState
from app.services import licensing

router = APIRouter(prefix="/api/license", tags=["licence"])

# Wrong-PIN throttle: pairing is only open while unpaired, but a 6-digit PIN
# must not be brute-forceable in that window.
_PAIR_MAX_FAILURES = 5
_PAIR_LOCKOUT_SECONDS = 900
_pair_failures: list[float] = []


async def _load(session: AsyncSession) -> LicenseState | None:
    result = await session.execute(
        select(LicenseState).where(LicenseState.server_id == settings.license_server_id)
    )
    return result.scalar_one_or_none()


class PairRequest(BaseModel):
    pin: str
    public_key: str  # base64 raw ECDSA P-256 point (0x04||X||Y)


class ApproveRequest(BaseModel):
    period: str        # "YYYY-MM" the phone believes is current
    issued_at: str     # ISO-8601 UTC timestamp the phone signed
    signature: str     # base64 raw r||s over approval_message(...)


@router.get("/status")
async def status(session: AsyncSession = Depends(get_session)) -> dict:
    return licensing.status_dict(await _load(session))


@router.post("/pair")
async def pair(body: PairRequest, session: AsyncSession = Depends(get_session)) -> dict:
    if not settings.license_pairing_pin:
        raise HTTPException(status_code=403, detail="Pairing is disabled on this server.")
    state = await _load(session)
    if state and state.public_key:
        raise HTTPException(status_code=409, detail="This server is already paired to a phone.")
    now_mono = time.monotonic()
    _pair_failures[:] = [t for t in _pair_failures if now_mono - t < _PAIR_LOCKOUT_SECONDS]
    if len(_pair_failures) >= _PAIR_MAX_FAILURES:
        raise HTTPException(status_code=429, detail="Too many wrong PINs; pairing locked for 15 minutes.")
    if body.pin != settings.license_pairing_pin:
        _pair_failures.append(now_mono)
        raise HTTPException(status_code=401, detail="Incorrect pairing PIN.")
    # Validate the key parses before storing.
    if not licensing._load_public_key_safe(body.public_key):
        raise HTTPException(status_code=400, detail="Invalid public key.")

    now = datetime.now(timezone.utc)
    if state is None:
        state = LicenseState(server_id=settings.license_server_id)
        session.add(state)
    state.public_key = body.public_key
    state.paired_at = now
    await session.commit()
    return {"ok": True, "paired": True, "server_id": settings.license_server_id}


@router.post("/approve")
async def approve(body: ApproveRequest, session: AsyncSession = Depends(get_session)) -> dict:
    state = await _load(session)
    if state is None or not state.public_key:
        raise HTTPException(status_code=409, detail="Server is not paired to a phone yet.")

    now = datetime.now(timezone.utc)
    expected_period = licensing.current_period(now)
    if body.period != expected_period:
        raise HTTPException(
            status_code=409,
            detail=f"Wrong cycle: this server expects {expected_period}.",
        )

    # Freshness: blunt replay of a captured approval.
    try:
        issued = datetime.fromisoformat(body.issued_at.replace("Z", "+00:00"))
        if issued.tzinfo is None:
            issued = issued.replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Bad issued_at timestamp.")
    if abs((now - issued).total_seconds()) > settings.license_approval_window_seconds:
        raise HTTPException(status_code=400, detail="Approval timestamp is stale; try again.")

    message = licensing.approval_message(settings.license_server_id, body.period, body.issued_at)
    if not licensing.verify_signature(state.public_key, message, body.signature):
        raise HTTPException(status_code=401, detail="Signature does not match the paired phone.")

    state.period = body.period
    state.valid_until = licensing.cycle_end(body.period)
    state.approved_at = now
    await session.commit()
    return {
        "ok": True,
        "approved_period": state.period,
        "valid_until": state.valid_until.isoformat(),
    }

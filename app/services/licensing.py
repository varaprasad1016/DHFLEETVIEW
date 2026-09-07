"""Monthly licence: period maths, signature verification, and the gate the
tacho download listeners call.

Design
------
* A "cycle" runs from the 15th of a month at 00:00 UTC to the 15th of the next
  month. Before the 15th you are still inside the previous month's cycle.
* Only the owner's phone can approve a cycle: it signs a canonical message with
  an ECDSA P-256 private key that never leaves the device. The server stores
  only the public key, so it can never mint its own approval.
* Enforcement is hard: once now passes valid_until (the next 15th) with no new
  approval, is_licensed() is False and the listeners refuse tacho downloads.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from app.config import settings
from app.models.licensing import LicenseState


# --- period maths -----------------------------------------------------------

def current_period(now: datetime, renew_day: int | None = None) -> str:
    """The cycle id ("YYYY-MM") that `now` falls in: the year-month of the
    cycle's starting 15th."""
    day = renew_day or settings.license_renew_day
    y, m = now.year, now.month
    if now.day < day:
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return f"{y:04d}-{m:02d}"


def cycle_end(period: str, renew_day: int | None = None) -> datetime:
    """The instant a cycle lapses: the renew-day of the month *after* `period`,
    00:00 UTC."""
    day = renew_day or settings.license_renew_day
    y, m = (int(x) for x in period.split("-"))
    m += 1
    if m == 13:
        m, y = 1, y + 1
    return datetime(y, m, day, 0, 0, 0, tzinfo=timezone.utc)


def approval_message(server_id: str, period: str, issued_at_iso: str) -> str:
    """Canonical string the phone signs and the server reconstructs."""
    return f"TACHO-LICENSE|{server_id}|{period}|{issued_at_iso}"


# --- signature verification -------------------------------------------------

def _load_public_key(public_key_b64: str) -> ec.EllipticCurvePublicKey:
    raw = base64.b64decode(public_key_b64)
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)


def _load_public_key_safe(public_key_b64: str) -> bool:
    """True when the base64 decodes to a valid P-256 public point."""
    try:
        _load_public_key(public_key_b64)
        return True
    except (ValueError, TypeError):
        return False


def verify_signature(public_key_b64: str, message: str, signature_b64: str) -> bool:
    """Verify a WebCrypto ECDSA/P-256/SHA-256 signature. WebCrypto emits the
    raw r||s (64 bytes); convert to DER for `cryptography`."""
    try:
        raw = base64.b64decode(signature_b64)
        if len(raw) != 64:
            return False
        r = int.from_bytes(raw[:32], "big")
        s = int.from_bytes(raw[32:], "big")
        der = utils.encode_dss_signature(r, s)
        _load_public_key(public_key_b64).verify(
            der, message.encode("utf-8"), ec.ECDSA(hashes.SHA256())
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


# --- the gate ---------------------------------------------------------------

def is_licensed(state: LicenseState | None, now: datetime | None = None) -> bool:
    """True when tacho downloads are permitted. Enforcement can be disabled in
    dev via LICENSE_ENFORCE=false."""
    if not settings.license_enforce:
        return True
    if state is None or not state.public_key or state.valid_until is None:
        return False
    now = now or datetime.now(timezone.utc)
    return now < state.valid_until


def status_dict(state: LicenseState | None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    period = current_period(now)
    licensed = is_licensed(state, now)
    valid_until = state.valid_until if state else None
    seconds_left = (
        int((valid_until - now).total_seconds())
        if (valid_until and valid_until > now)
        else 0
    )
    return {
        "server_id": settings.license_server_id,
        "enforced": settings.license_enforce,
        "paired": bool(state and state.public_key),
        "licensed": licensed,
        "current_period": period,
        "approved_period": state.period if state else None,
        "valid_until": valid_until.isoformat() if valid_until else None,
        "seconds_remaining": seconds_left,
        "days_remaining": seconds_left // 86400,
        "renew_day": settings.license_renew_day,
    }

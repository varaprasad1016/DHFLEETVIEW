"""Who is calling: office staff (a DH FleetView / Traccar session) or a driver
(a driver-app token issued after name + PIN sign-in).

Office staff never get separate credentials here. Their browser already holds
the Traccar session cookie for this origin, so we ask Traccar who it belongs
to (`GET /api/session`) and cache the answer briefly. Drivers get an opaque
`drv_` bearer token; only its SHA-256 is stored.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.config import settings

DRIVER_TOKEN_PREFIX = "drv_"
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


@dataclass(frozen=True)
class Principal:
    kind: str                 # "manager" | "driver"
    name: str                 # Traccar user name/email, or the driver's account name
    user_id: int | None = None
    driver_id: str | None = None
    administrator: bool = False
    email: str = ""
    # Drivers: the company driver records (DH FleetView driver ids) this login belongs to.
    driver_ids: tuple[int, ...] = ()
    cookie: str = ""          # the caller's DH FleetView session, to act as them in Traccar
    authorization: str = ""

    @property
    def is_manager(self) -> bool:
        return self.kind == "manager"


# --- driver PINs & tokens --------------------------------------------------------

def generate_pin() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(pin.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def new_driver_token() -> tuple[str, str]:
    """(token for the device, sha256 hex to store)."""
    token = DRIVER_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, token_hash(token)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- office staff via Traccar ----------------------------------------------------

_CACHE_TTL = 30.0
_cache: dict[str, tuple[float, dict | None]] = {}


def session_cookie(cookie_header: str) -> str:
    """Only forward Traccar's session cookie, never anything else the browser holds."""
    parts = [c.strip() for c in cookie_header.split(";")]
    return "; ".join(c for c in parts if c.upper().startswith("JSESSIONID="))


def _traccar_get(path: str, cookie: str, authorization: str):
    headers = {"Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    if authorization:
        headers["Authorization"] = authorization
    req = urllib.request.Request(settings.traccar_url.rstrip("/") + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            return None  # not signed in
        raise
    # URLError (Traccar down) propagates: callers turn it into 503, never into access.


async def traccar_get(principal: "Principal", path: str):
    """GET a Traccar API path as the signed-in office user, so Traccar's own
    permissions decide what they can see. None when not found / not allowed."""
    return await asyncio.to_thread(_traccar_get, path, principal.cookie, principal.authorization)


async def traccar_user(cookie_header: str | None, authorization: str | None) -> dict | None:
    cookie = session_cookie(cookie_header or "")
    auth = authorization if authorization and not authorization.startswith("Bearer " + DRIVER_TOKEN_PREFIX) else ""
    if not cookie and not auth:
        return None
    key = hashlib.sha256(f"{cookie}|{auth}".encode()).hexdigest()
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    user = await asyncio.to_thread(_traccar_get, "/api/session", cookie, auth)
    if len(_cache) > 2000:
        _cache.clear()
    _cache[key] = (now + _CACHE_TTL, user)
    return user


_list_cache: dict[str, tuple[float, list[dict]]] = {}


async def _visible_list(principal: "Principal", path: str) -> list[dict]:
    key = hashlib.sha256(f"{path}|{principal.cookie}|{principal.authorization}".encode()).hexdigest()
    now = time.monotonic()
    hit = _list_cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    items = await traccar_get(principal, path)
    items = [d for d in (items or []) if isinstance(d, dict) and "id" in d]
    if len(_list_cache) > 2000:
        _list_cache.clear()
    _list_cache[key] = (now + _CACHE_TTL, items)
    return items


async def visible_drivers(principal: "Principal") -> list[dict]:
    """The DH FleetView drivers linked to this office user (the ones they added)."""
    return await _visible_list(principal, "/api/drivers")


async def visible_devices(principal: "Principal") -> list[dict]:
    """The DH FleetView vehicles (devices) this office user can see."""
    return await _visible_list(principal, "/api/devices")


def manager_allowed(user: dict) -> bool:
    if user.get("disabled"):
        return False
    role = (settings.manager_role or "manager").lower()
    if role == "user":
        return True
    if user.get("administrator"):
        return True
    if role == "manager":
        return (user.get("userLimit") or 0) != 0
    return False


def allowed_origins() -> list[str]:
    return [o.strip().rstrip("/") for o in (settings.allowed_origins or "").split(",") if o.strip()]

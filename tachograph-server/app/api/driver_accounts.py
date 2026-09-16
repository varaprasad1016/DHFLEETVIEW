"""Driver sign-in for the driver screens, and PIN management for office staff.

Drivers are created on the DH FleetView Drivers page. Each can get an app PIN
there; this service stores only the PIN hash and device sessions, linked by the
Traccar driver id. The main DH FleetView login sends anything that isn't an
email address here first, so drivers and office staff share one login screen.

* /api/driver/auth/*                   — drivers: sign in (name or driver ID + PIN), check, sign out.
                                         Not licence-gated, so a driver still reaches the "locked" screen.
* /api/driver-accounts/traccar[...]    — office staff: PIN + app access per DH FleetView driver.
* /api/driver-accounts[...]            — older name-only accounts (kept for existing data).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver, require_license, require_manager
from app.config import settings
from app.database import get_session
from app.models.driver_auth import DriverAccount, DriverSession
from app.services import auth
from app.services.auth import Principal

auth_router = APIRouter(prefix="/api/driver/auth", tags=["driver auth"])
accounts_router = APIRouter(prefix="/api/driver-accounts", tags=["driver accounts"],
                            dependencies=[Depends(require_license), Depends(require_manager)])

_MAX_FAILURES = 5
_LOCK_MINUTES = 15
_GLOBAL_WINDOW = 900.0
_GLOBAL_MAX = 50
_global_failures: list[float] = []
_DUMMY_HASH = auth.hash_pin("000000")


def _clean_name(name: str) -> str:
    return " ".join(name.split())


class LoginIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)  # driver name or DH FleetView driver identifier
    pin: str = Field(..., min_length=4, max_length=12)


@auth_router.post("/login")
async def login(body: LoginIn, request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    now_mono = time.monotonic()
    _global_failures[:] = [t for t in _global_failures if now_mono - t < _GLOBAL_WINDOW]
    if len(_global_failures) >= _GLOBAL_MAX:
        raise HTTPException(status_code=429, detail="Too many failed sign-ins. Try again in a few minutes.")

    now = datetime.now(timezone.utc)
    ident = _clean_name(body.name).lower()
    matches = (await session.execute(
        select(DriverAccount).where(or_(func.lower(DriverAccount.unique_id) == ident,
                                        func.lower(DriverAccount.name) == ident))
    )).scalars().all()
    # The identifier is unique; a name may not be.
    by_id = [a for a in matches if (a.unique_id or "").lower() == ident]
    candidates = by_id or matches
    wrong = "Name or PIN is wrong."
    if len(candidates) > 1:
        auth.verify_pin(body.pin, _DUMMY_HASH)
        raise HTTPException(status_code=401, detail="More than one driver has that name. Sign in with your driver ID.")
    account = candidates[0] if candidates else None
    if account is None:
        auth.verify_pin(body.pin, _DUMMY_HASH)  # same work either way
        _global_failures.append(now_mono)
        raise HTTPException(status_code=401, detail=wrong)
    if account.locked_until and account.locked_until > now:
        raise HTTPException(status_code=429, detail="Too many wrong PINs. Try again in 15 minutes or ask your office to reset it.")
    if not auth.verify_pin(body.pin.strip(), account.pin_hash):
        account.failed_attempts = (account.failed_attempts or 0) + 1
        if account.failed_attempts >= _MAX_FAILURES:
            account.locked_until = now + timedelta(minutes=_LOCK_MINUTES)
            account.failed_attempts = 0
        await session.commit()
        _global_failures.append(now_mono)
        raise HTTPException(status_code=401, detail=wrong)
    if not account.active:
        raise HTTPException(status_code=403, detail="This driver account is disabled. Contact your office.")

    token, digest = auth.new_driver_token()
    account.failed_attempts = 0
    account.locked_until = None
    account.last_login_at = now
    session.add(DriverSession(
        account_id=account.id, token_hash=digest, last_seen_at=now,
        user_agent=(request.headers.get("user-agent") or "")[:200],
        expires_at=now + timedelta(days=settings.driver_session_days),
    ))
    await session.commit()
    return {"token": token, "driver": {"id": str(account.id), "name": account.name}}


@auth_router.get("/me")
async def me(principal: Principal = Depends(require_driver)) -> dict:
    return {"driver": {"id": principal.driver_id, "name": principal.name}}


@auth_router.post("/logout")
async def logout(request: Request, principal: Principal = Depends(require_driver),
                 session: AsyncSession = Depends(get_session)) -> dict:
    token = (request.headers.get("authorization") or "")[len("Bearer "):].strip()
    await session.execute(delete(DriverSession).where(DriverSession.token_hash == auth.token_hash(token)))
    await session.commit()
    return {"ok": True}


# --- office admin --------------------------------------------------------------------

class AccountIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    pin: str | None = Field(default=None, pattern=r"^\d{6}$")


class AccountPatch(BaseModel):
    active: bool | None = None
    phone: str | None = Field(default=None, max_length=30)


async def _summary(session: AsyncSession, a: DriverAccount) -> dict:
    """Account status for the office. Never includes the PIN hash."""
    devices = (await session.execute(
        select(func.count()).select_from(DriverSession).where(
            DriverSession.account_id == a.id, DriverSession.expires_at > datetime.now(timezone.utc))
    )).scalar_one()
    return {
        "id": str(a.id), "name": a.name, "phone": a.phone, "active": a.active,
        "traccar_driver_id": a.traccar_driver_id, "unique_id": a.unique_id,
        "locked": bool(a.locked_until and a.locked_until > datetime.now(timezone.utc)),
        "devices": devices,
        "last_login_at": a.last_login_at.isoformat() if a.last_login_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


async def _get(session: AsyncSession, account_id: uuid.UUID) -> DriverAccount:
    a = (await session.execute(select(DriverAccount).where(DriverAccount.id == account_id))).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail="Driver account not found.")
    return a


@accounts_router.get("")
async def list_accounts(session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.execute(select(DriverAccount).order_by(func.lower(DriverAccount.name)))).scalars().all()
    return [await _summary(session, a) for a in rows]


@accounts_router.post("", status_code=201)
async def create_account(body: AccountIn, principal: Principal = Depends(require_manager),
                         session: AsyncSession = Depends(get_session)) -> dict:
    existing = (await session.execute(
        select(DriverAccount.id).where(func.lower(DriverAccount.name) == _clean_name(body.name).lower())
    )).first()
    if existing:
        raise HTTPException(status_code=409, detail="A driver with that name already exists.")
    pin = body.pin or auth.generate_pin()
    a = DriverAccount(name=_clean_name(body.name), phone=(body.phone or "").strip() or None,
                      pin_hash=auth.hash_pin(pin), created_by=principal.name)
    session.add(a)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A driver with that name already exists.")
    await session.refresh(a)
    return {**(await _summary(session, a)), "pin": pin}


@accounts_router.post("/{account_id}/reset-pin")
async def reset_pin(account_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    """New PIN shown once; signs the driver out of every device."""
    a = await _get(session, account_id)
    pin = auth.generate_pin()
    a.pin_hash = auth.hash_pin(pin)
    a.failed_attempts = 0
    a.locked_until = None
    await session.execute(delete(DriverSession).where(DriverSession.account_id == a.id))
    await session.commit()
    return {**(await _summary(session, a)), "pin": pin}


@accounts_router.patch("/{account_id}")
async def update_account(account_id: uuid.UUID, body: AccountPatch,
                         session: AsyncSession = Depends(get_session)) -> dict:
    a = await _get(session, account_id)
    if body.active is not None:
        a.active = body.active
        if not body.active:
            await session.execute(delete(DriverSession).where(DriverSession.account_id == a.id))
    if body.phone is not None:
        a.phone = body.phone.strip() or None
    await session.commit()
    return await _summary(session, a)


@accounts_router.post("/{account_id}/sign-out")
async def sign_out_everywhere(account_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    a = await _get(session, account_id)
    await session.execute(delete(DriverSession).where(DriverSession.account_id == a.id))
    await session.commit()
    return await _summary(session, a)


# --- PINs for DH FleetView drivers --------------------------------------------------------

class TraccarPinIn(BaseModel):
    pin: str | None = Field(default=None, pattern=r"^\d{6}$")  # None = keep the current PIN
    active: bool | None = None


@accounts_router.get("/traccar")
async def list_traccar_accounts(session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.execute(
        select(DriverAccount).where(DriverAccount.traccar_driver_id.is_not(None))
    )).scalars().all()
    return [await _summary(session, a) for a in rows]


@accounts_router.get("/traccar/{driver_id}")
async def get_traccar_account(driver_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    a = (await session.execute(
        select(DriverAccount).where(DriverAccount.traccar_driver_id == driver_id)
    )).scalar_one_or_none()
    return await _summary(session, a) if a else {"traccar_driver_id": driver_id, "has_account": False}


@accounts_router.put("/traccar/{driver_id}")
async def set_traccar_account(driver_id: int, body: TraccarPinIn,
                              principal: Principal = Depends(require_manager),
                              session: AsyncSession = Depends(get_session)) -> dict:
    """Set a driver's app PIN and/or app access. The driver's name and identifier are
    read from DH FleetView as the signed-in user, so a user can only give PINs to
    drivers they can see there."""
    driver = await auth.traccar_get(principal, f"/api/drivers/{driver_id}")
    if not driver or not driver.get("name"):
        raise HTTPException(status_code=404, detail="Driver not found in DH FleetView.")
    a = (await session.execute(
        select(DriverAccount).where(DriverAccount.traccar_driver_id == driver_id)
    )).scalar_one_or_none()
    if a is None:
        if not body.pin:
            raise HTTPException(status_code=400, detail="Enter a 6-digit PIN to give this driver app access.")
        a = DriverAccount(traccar_driver_id=driver_id, name=_clean_name(driver["name"]),
                          unique_id=(driver.get("uniqueId") or "").strip() or None,
                          pin_hash=auth.hash_pin(body.pin), created_by=principal.name)
        session.add(a)
    else:
        a.name = _clean_name(driver["name"])
        a.unique_id = (driver.get("uniqueId") or "").strip() or None
        if body.pin:
            a.pin_hash = auth.hash_pin(body.pin)
            a.failed_attempts = 0
            a.locked_until = None
            await session.execute(delete(DriverSession).where(DriverSession.account_id == a.id))
    if body.active is not None:
        a.active = body.active
        if not body.active and a.id is not None:
            await session.execute(delete(DriverSession).where(DriverSession.account_id == a.id))
    await session.commit()
    await session.refresh(a)
    return await _summary(session, a)


@accounts_router.post("/traccar-sync")
async def sync_traccar_accounts(principal: Principal = Depends(require_manager),
                                session: AsyncSession = Depends(get_session)) -> dict:
    """Keep names/IDs in step with DH FleetView and switch off app access for drivers
    that were deleted there. Only an administrator sees every driver, so only an
    administrator's sync may disable anything."""
    drivers = await auth.traccar_get(principal, "/api/drivers?all=true" if principal.administrator else "/api/drivers")
    if not isinstance(drivers, list):
        raise HTTPException(status_code=502, detail="Couldn't read drivers from DH FleetView.")
    by_id = {d["id"]: d for d in drivers if "id" in d}
    renamed = disabled = 0
    rows = (await session.execute(
        select(DriverAccount).where(DriverAccount.traccar_driver_id.is_not(None))
    )).scalars().all()
    for a in rows:
        d = by_id.get(a.traccar_driver_id)
        if d:
            name, uid = _clean_name(d.get("name") or a.name), (d.get("uniqueId") or "").strip() or None
            if (name, uid) != (a.name, a.unique_id):
                a.name, a.unique_id = name, uid
                renamed += 1
        elif principal.administrator and a.active:
            a.active = False
            await session.execute(delete(DriverSession).where(DriverSession.account_id == a.id))
            disabled += 1
    await session.commit()
    return {"drivers": len(by_id), "updated": renamed, "disabled": disabled}

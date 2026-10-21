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

import re
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver, require_license, require_manager, require_module
from app.config import settings
from app.database import get_session
from app.models.driver_auth import DriverAccount, DriverMembership, DriverSession
from app.services import auth, modules
from app.services.auth import Principal

auth_router = APIRouter(prefix="/api/driver/auth", tags=["driver auth"])
accounts_router = APIRouter(prefix="/api/driver-accounts", tags=["driver accounts"],
                            dependencies=[Depends(require_license), Depends(require_manager),
                                          Depends(require_module("driver_pins"))])

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
    ident_id = _norm_id(body.name)
    matches = (await session.execute(
        select(DriverAccount).where(or_(func.upper(func.replace(DriverAccount.unique_id, " ", "")) == ident_id,
                                        func.lower(DriverAccount.name) == ident))
    )).scalars().all()
    # The identifier (driver card number / mobile) is unique; a name may not be.
    by_id = [a for a in matches if _norm_id(a.unique_id) == ident_id]
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
    links = (await session.execute(
        select(DriverMembership.active).where(DriverMembership.account_id == account.id))).scalars().all()
    if links and not any(links):
        raise HTTPException(status_code=403, detail="Your companies have switched off your driver app access.")

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


# --- PINs for DH FleetView drivers (one login per person, one membership per company) ---------

def _norm_id(value: str | None) -> str | None:
    """Identifiers compare without spaces and case (driver card numbers are often typed with spaces)."""
    cleaned = re.sub(r"\s+", "", value or "").upper()
    return cleaned or None


class TraccarPinIn(BaseModel):
    pin: str | None = Field(default=None, pattern=r"^\d{6}$")  # None = keep the current PIN
    active: bool | None = None


async def _visible_driver(principal: Principal, driver_id: int) -> dict:
    driver = await auth.traccar_get(principal, f"/api/drivers/{driver_id}")
    if not driver or not driver.get("name"):
        raise HTTPException(status_code=404, detail="Driver not found in your DH FleetView drivers.")
    return driver


async def _account_by_identifier(session: AsyncSession, identifier: str) -> DriverAccount | None:
    return (await session.execute(
        select(DriverAccount).where(func.upper(func.replace(DriverAccount.unique_id, " ", "")) == identifier)
    )).scalars().first()


async def _other_companies(session: AsyncSession, account_id: uuid.UUID, except_driver_id: int | None) -> int:
    stmt = select(func.count()).select_from(DriverMembership).where(
        DriverMembership.account_id == account_id, DriverMembership.active.is_(True))
    if except_driver_id is not None:
        stmt = stmt.where(DriverMembership.traccar_driver_id != except_driver_id)
    return (await session.execute(stmt)).scalar_one()


async def _sync_identity(session: AsyncSession, m: DriverMembership, a: DriverAccount, driver: dict) -> bool:
    """Copy the DH FleetView driver's name and identifier onto their driver login.

    The identifier is edited on the DH FleetView driver (e.g. a driver card number
    added later); the driver app and their tachograph hours read it from the login.
    A login shared with another company keeps its identifier, and one that would
    clash with another login is left alone."""
    if await _other_companies(session, a.id, m.traccar_driver_id) > 0:
        return False
    changed = False
    name = _clean_name(driver.get("name") or a.name)
    if name != a.name:
        a.name = name
        changed = True
    identifier = _norm_id(driver.get("uniqueId"))
    if identifier and identifier != _norm_id(a.unique_id):
        clash = await _account_by_identifier(session, identifier)
        if clash is None or clash.id == a.id:
            a.unique_id = identifier
            changed = True
    return changed


async def _link_status(session: AsyncSession, principal: Principal, m: DriverMembership, a: DriverAccount) -> dict:
    others = await _other_companies(session, a.id, m.traccar_driver_id)
    return {
        **(await _summary(session, a)),
        "traccar_driver_id": m.traccar_driver_id,
        "active": bool(m.active and a.active),
        "shared": others > 0,
        "other_companies": others,
        "can_change_pin": others == 0 or modules.is_super_admin(principal),
    }


@accounts_router.get("/traccar")
async def list_traccar_accounts(principal: Principal = Depends(require_manager),
                                session: AsyncSession = Depends(get_session)) -> list[dict]:
    """App status for the drivers this user can see in DH FleetView only."""
    ids = [int(d["id"]) for d in await auth.visible_drivers(principal)]
    if not ids:
        return []
    rows = (await session.execute(
        select(DriverMembership, DriverAccount).join(DriverAccount, DriverAccount.id == DriverMembership.account_id)
        .where(DriverMembership.traccar_driver_id.in_(ids))
    )).all()
    return [await _link_status(session, principal, m, a) for m, a in rows]


@accounts_router.get("/traccar/{driver_id}")
async def get_traccar_account(driver_id: int, principal: Principal = Depends(require_manager),
                              session: AsyncSession = Depends(get_session)) -> dict:
    driver = await _visible_driver(principal, driver_id)
    row = (await session.execute(
        select(DriverMembership, DriverAccount).join(DriverAccount, DriverAccount.id == DriverMembership.account_id)
        .where(DriverMembership.traccar_driver_id == driver_id)
    )).first()
    if row:
        if await _sync_identity(session, row[0], row[1], driver):
            await session.commit()
            await session.refresh(row[1])
        return await _link_status(session, principal, *row)
    identifier = _norm_id(driver.get("uniqueId"))
    existing = await _account_by_identifier(session, identifier) if identifier else None
    return {"traccar_driver_id": driver_id, "has_account": False,
            # Another company already gave this person a login: saving links them.
            "existing_login": existing is not None}


@accounts_router.put("/traccar/{driver_id}")
async def set_traccar_account(driver_id: int, body: TraccarPinIn,
                              principal: Principal = Depends(require_manager),
                              session: AsyncSession = Depends(get_session)) -> dict:
    """Give one of your drivers app access, link them to their existing login if
    another company already set one up (same identifier), set a PIN, or switch
    access off for your company."""
    driver = await _visible_driver(principal, driver_id)
    identifier = _norm_id(driver.get("uniqueId"))
    if not identifier:
        raise HTTPException(status_code=400, detail="Add the driver's identifier first (driver card number, or mobile number).")
    super_admin = modules.is_super_admin(principal)
    now_sessions_off = False

    row = (await session.execute(
        select(DriverMembership, DriverAccount).join(DriverAccount, DriverAccount.id == DriverMembership.account_id)
        .where(DriverMembership.traccar_driver_id == driver_id)
    )).first()
    if row is None:
        a = await _account_by_identifier(session, identifier)
        if a is None:
            if not body.pin:
                raise HTTPException(status_code=400, detail="Enter a 6-digit PIN to give this driver app access.")
            a = DriverAccount(name=_clean_name(driver["name"]), unique_id=identifier,
                              pin_hash=auth.hash_pin(body.pin), created_by=principal.name)
            session.add(a)
            await session.flush()
        elif body.pin:
            if await _other_companies(session, a.id, None) > 0 and not super_admin:
                raise HTTPException(status_code=403, detail={
                    "error": "shared_login",
                    "message": "This driver already has a driver login from another company. They'll see your "
                               "jobs with their existing PIN; only the super administrator can change it."})
            a.pin_hash = auth.hash_pin(body.pin)
            now_sessions_off = True
        m = DriverMembership(account_id=a.id, traccar_driver_id=driver_id, company_label=principal.name,
                             owner_user_id=principal.user_id, active=True)
        session.add(m)
    else:
        m, a = row
        others = await _other_companies(session, a.id, driver_id)
        if _norm_id(a.unique_id) != identifier:
            clash = await _account_by_identifier(session, identifier)
            if clash is not None and clash.id != a.id:
                raise HTTPException(status_code=409, detail="That identifier already belongs to another driver login.")
            if others > 0 and not super_admin:
                raise HTTPException(status_code=409, detail="This driver's login is shared with another company, so their identifier can't change here.")
            a.unique_id = identifier
        if others == 0:
            a.name = _clean_name(driver["name"])
        if body.pin:
            if others > 0 and not super_admin:
                raise HTTPException(status_code=403, detail={
                    "error": "shared_login",
                    "message": "This driver also works for another company, so only the super administrator can change their PIN."})
            a.pin_hash = auth.hash_pin(body.pin)
            now_sessions_off = True
    if body.pin:
        a.failed_attempts = 0
        a.locked_until = None
    if body.active is not None:
        m.active = body.active
    await session.flush()
    if now_sessions_off or (body.active is False and await _other_companies(session, a.id, None) == 0):
        await session.execute(delete(DriverSession).where(DriverSession.account_id == a.id))
    await session.commit()
    await session.refresh(a)
    await session.refresh(m)
    return await _link_status(session, principal, m, a)


@accounts_router.post("/traccar-sync")
async def sync_traccar_accounts(principal: Principal = Depends(require_manager),
                                session: AsyncSession = Depends(get_session)) -> dict:
    """Switch off app access for drivers deleted in DH FleetView. Only an
    administrator sees every driver, so only an administrator's sync may disable."""
    drivers = await auth.traccar_get(principal, "/api/drivers?all=true" if principal.administrator else "/api/drivers")
    if not isinstance(drivers, list):
        raise HTTPException(status_code=502, detail="Couldn't read drivers from DH FleetView.")
    by_id = {int(d["id"]): d for d in drivers if "id" in d}
    updated = disabled = 0
    rows = (await session.execute(
        select(DriverMembership, DriverAccount).join(DriverAccount, DriverAccount.id == DriverMembership.account_id)
    )).all()
    for m, a in rows:
        d = by_id.get(m.traccar_driver_id)
        if d:
            if await _sync_identity(session, m, a, d):
                updated += 1
        elif principal.administrator and m.active:
            m.active = False
            disabled += 1
            if await _other_companies(session, a.id, m.traccar_driver_id) == 0:
                await session.execute(delete(DriverSession).where(DriverSession.account_id == a.id))
    await session.commit()
    return {"drivers": len(by_id), "updated": updated, "disabled": disabled}

"""Shared API dependencies.

The single most important one is `require_license`: every UK-compliance feature
(walkaround checks, DVLA/DVSA reminders, Clean Air Zone, tacho compliance,
Earned Recognition) depends on it, so the one monthly phone approval locks or
unlocks the whole suite together. GPS/Traccar is a separate service and is never
gated here.
"""

from __future__ import annotations

import urllib.error
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models.driver_auth import DriverAccount, DriverSession
from app.models.licensing import LicenseState
from app.services import auth, licensing
from app.services.auth import Principal


async def load_license_state(session: AsyncSession) -> LicenseState | None:
    result = await session.execute(
        select(LicenseState).where(LicenseState.server_id == settings.license_server_id)
    )
    return result.scalar_one_or_none()


async def require_license(session: AsyncSession = Depends(get_session)) -> LicenseState | None:
    """Gate a route behind the monthly licence. Raises 403 with the current
    licence status when suspended, so the UI can show the unlock screen and the
    phone-approval link. Returns the LicenseState for handlers that want it."""
    state = await load_license_state(session)
    if not licensing.is_licensed(state):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "licence_suspended",
                "message": "This compliance feature is locked. Approve this month's "
                           "licence from your paired phone to unlock it.",
                "license": licensing.status_dict(state),
                "approver_url": "/tacho/approver",
            },
        )
    return state


# --- who is calling ---------------------------------------------------------------

def _login_required(who: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": "login_required",
            "who": who,
            "message": "Sign in to DH FleetView to use this." if who == "manager"
                       else "Sign in to the driver app to use this.",
            "login_url": "/",
        },
    )


async def _driver_principal(request: Request, session: AsyncSession) -> Principal | None:
    header = request.headers.get("authorization") or ""
    if not header.startswith("Bearer " + auth.DRIVER_TOKEN_PREFIX):
        return None
    now = datetime.now(timezone.utc)
    row = (await session.execute(
        select(DriverSession, DriverAccount)
        .join(DriverAccount, DriverAccount.id == DriverSession.account_id)
        .where(DriverSession.token_hash == auth.token_hash(header[len("Bearer "):].strip()))
    )).first()
    if row is None:
        raise _login_required("driver")
    sess, account = row
    if not account.active or sess.expires_at <= now:
        raise _login_required("driver")
    # Touch at most every 10 minutes; sliding expiry keeps daily users signed in.
    if sess.last_seen_at is None or now - sess.last_seen_at > timedelta(minutes=10):
        sess.last_seen_at = now
        sess.expires_at = now + timedelta(days=settings.driver_session_days)
        await session.commit()
    return Principal(kind="driver", name=account.name, driver_id=str(account.id))


async def _manager_principal(request: Request) -> Principal | None:
    try:
        user = await auth.traccar_user(request.headers.get("cookie"), request.headers.get("authorization"))
    except (urllib.error.URLError, OSError, ValueError):
        raise HTTPException(status_code=503, detail="Can't reach DH FleetView to check your sign-in. Try again shortly.")
    if user is None:
        return None
    if not auth.manager_allowed(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "not_manager",
                    "message": "Your DH FleetView account doesn't have access to the office compliance tools."},
        )
    # Cookie-authenticated writes must come from our own pages (CSRF guard).
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("cookie"):
        origin = (request.headers.get("origin") or "").rstrip("/")
        if origin and origin not in auth.allowed_origins() and origin != f"{request.url.scheme}://{request.url.netloc}":
            raise HTTPException(status_code=403, detail="Cross-site request refused.")
    authorization = request.headers.get("authorization") or ""
    return Principal(kind="manager", name=user.get("name") or user.get("email") or "Office",
                     user_id=user.get("id"), administrator=bool(user.get("administrator")),
                     email=user.get("email") or "",
                     cookie=auth.session_cookie(request.headers.get("cookie") or ""),
                     authorization="" if authorization.startswith("Bearer " + auth.DRIVER_TOKEN_PREFIX) else authorization)


async def require_manager(request: Request) -> Principal:
    """Office staff signed in to DH FleetView."""
    principal = await _manager_principal(request)
    if principal is None:
        raise _login_required("manager")
    return principal


async def require_driver(request: Request, session: AsyncSession = Depends(get_session)) -> Principal:
    """A driver signed in to the driver app."""
    principal = await _driver_principal(request, session)
    if principal is None:
        raise _login_required("driver")
    return principal


async def require_driver_or_manager(request: Request, session: AsyncSession = Depends(get_session)) -> Principal:
    principal = await _driver_principal(request, session)
    if principal is not None:
        return principal
    principal = await _manager_principal(request)
    if principal is None:
        raise _login_required("manager")
    return principal


def ensure_own(principal: Principal, driver_name: str | None) -> None:
    """Drivers may only touch their own shifts, jobs and files; office staff may touch any."""
    if principal.is_manager:
        return
    if (driver_name or "").strip().lower() != principal.name.strip().lower():
        raise HTTPException(status_code=404, detail="Not found.")


# --- module access -------------------------------------------------------------------------

def require_module(key: str):
    """Refuse an office user's requests to a module the super administrator hasn't
    given them. Drivers and the super administrator are never limited here; the
    route's own auth dependency still decides who may call it at all."""
    from app.services import modules

    async def dependency(request: Request, session: AsyncSession = Depends(get_session)) -> None:
        if await _driver_principal(request, session) is not None:
            return
        principal = await _manager_principal(request)
        if principal is None or modules.is_super_admin(principal):
            return
        flags, _ = await modules.get_user_flags(session, principal.user_id)
        if not flags.get(key, True):
            label = next((lbl for k, lbl, _ in modules.MODULES if k == key), key)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "module_disabled", "module": key,
                        "message": f"{label} isn't switched on for your account. Ask your administrator."},
            )
    dependency.__name__ = f"require_module_{key}"
    return dependency

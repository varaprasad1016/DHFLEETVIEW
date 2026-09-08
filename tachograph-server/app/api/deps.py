"""Shared API dependencies.

The single most important one is `require_license`: every UK-compliance feature
(walkaround checks, DVLA/DVSA reminders, Clean Air Zone, tacho compliance,
Earned Recognition) depends on it, so the one monthly phone approval locks or
unlocks the whole suite together. GPS/Traccar is a separate service and is never
gated here.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models.licensing import LicenseState
from app.services import licensing


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

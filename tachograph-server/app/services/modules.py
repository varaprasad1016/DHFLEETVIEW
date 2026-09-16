"""Module access per DH FleetView user.

The super administrator ticks which Compliance hub modules each user can see,
on that user's page in DH FleetView (Settings > Users). A module that is off for
a user is hidden from them and its API refuses their requests.

Users with no saved choices see every module, so existing users keep working
until someone unticks a box. The super administrator always sees everything.
Drivers aren't DH FleetView users; their access is their PIN and app-access
switch, so module access doesn't apply to them.
"""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.settings import AppSetting

# (key, label, description) in Compliance hub order.
MODULES: list[tuple[str, str, str]] = [
    ("defects", "Defects", "Open defects and rectification"),
    ("walkaround_reports", "Walkaround reports", "All drivers' walkaround checks"),
    ("reminders", "MOT / tax reminders", "DVLA MOT, tax and Euro status"),
    ("caz", "Clean Air Zone", "ULEZ / CAZ exposure"),
    ("tacho", "Tacho compliance", "Drivers' hours, downloads, archive"),
    ("driver_app", "Driver App", "The driver screens link"),
    ("driver_pins", "Drivers & app PINs", "PIN section on Settings > Drivers"),
    ("jobs", "Job Management", "Send and manage driver jobs"),
    ("shifts", "Shift Reports", "Active shifts, history and photos"),
    ("earned_recognition", "Earned Recognition", "DVSA KPI dashboard (coming soon)"),
]
KEYS = {k for k, _, _ in MODULES}
ALL_ON = {k: True for k in KEYS}

_TTL = 10.0
_cache: dict[str, tuple[float, dict[str, bool], bool]] = {}


def _key(user_id: int) -> str:
    return f"modules:user:{int(user_id)}"


def _merge(stored: dict | None) -> dict[str, bool]:
    stored = stored or {}
    return {k: bool(stored.get(k, True)) for k, _, _ in MODULES}


async def get_user_flags(session: AsyncSession, user_id: int | None) -> tuple[dict[str, bool], bool]:
    """(flags, configured) for a DH FleetView user id."""
    if user_id is None:
        return dict(ALL_ON), False
    key = _key(user_id)
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1], hit[2]
    row = (await session.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
    flags, configured = _merge(row.value if row else None), row is not None
    if len(_cache) > 5000:
        _cache.clear()
    _cache[key] = (now + _TTL, flags, configured)
    return flags, configured


async def set_user_flags(session: AsyncSession, user_id: int, changes: dict[str, bool], updated_by: str) -> dict[str, bool]:
    key = _key(user_id)
    row = (await session.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
    flags = _merge(row.value if row else None)
    flags.update({k: bool(v) for k, v in changes.items() if k in KEYS})
    if row is None:
        session.add(AppSetting(key=key, value=flags, updated_by=updated_by))
    else:
        row.value = flags
        row.updated_by = updated_by
    await session.commit()
    _cache.pop(key, None)
    return flags


async def effective_flags(session: AsyncSession, principal) -> dict[str, bool]:
    """What this caller may see: everything for drivers and the super administrator."""
    if principal is None or not principal.is_manager or is_super_admin(principal):
        return dict(ALL_ON)
    flags, _ = await get_user_flags(session, principal.user_id)
    return flags


async def get_flags(session: AsyncSession) -> dict[str, bool]:
    """Kept for callers without a user (driver screens): everything on."""
    return dict(ALL_ON)


def is_super_admin(principal) -> bool:
    """A DH FleetView administrator; if SUPER_ADMIN_EMAILS is set, only those accounts."""
    if principal is None or not principal.is_manager or not principal.administrator:
        return False
    allowed = [e.strip().lower() for e in (settings.super_admin_emails or "").split(",") if e.strip()]
    return not allowed or (principal.email or "").lower() in allowed

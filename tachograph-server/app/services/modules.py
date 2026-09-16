"""Module switches: the super administrator turns each Compliance hub module on
or off for everyone. Off means the hub hides it and its API refuses requests.

Modules default to ON, so this changes nothing until someone unticks a box.
"""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.settings import AppSetting

SETTING_KEY = "modules"

# (key, label, description) in Compliance hub order.
MODULES: list[tuple[str, str, str]] = [
    ("defects", "Defects", "Open defects and rectification"),
    ("walkaround_reports", "Walkaround reports", "All drivers' walkaround checks"),
    ("reminders", "MOT / tax reminders", "DVLA MOT, tax and Euro status"),
    ("caz", "Clean Air Zone", "ULEZ / CAZ exposure"),
    ("tacho", "Tacho compliance", "Drivers' hours, downloads, archive"),
    ("driver_app", "Driver App", "Driver sign-in and the driver screens"),
    ("driver_pins", "Drivers & app PINs", "PIN section on Settings > Drivers"),
    ("jobs", "Job Management", "Send jobs; jobs in the driver app"),
    ("shifts", "Shift Reports", "Active shifts, history and photos"),
    ("earned_recognition", "Earned Recognition", "DVSA KPI dashboard (coming soon)"),
]
KEYS = {k for k, _, _ in MODULES}

_TTL = 10.0
_cache: tuple[float, dict[str, bool]] | None = None


def _merge(stored: dict | None) -> dict[str, bool]:
    stored = stored or {}
    return {k: bool(stored.get(k, True)) for k, _, _ in MODULES}


async def get_flags(session: AsyncSession) -> dict[str, bool]:
    global _cache
    now = time.monotonic()
    if _cache and _cache[0] > now:
        return _cache[1]
    row = (await session.execute(select(AppSetting).where(AppSetting.key == SETTING_KEY))).scalar_one_or_none()
    flags = _merge(row.value if row else None)
    _cache = (now + _TTL, flags)
    return flags


async def set_flags(session: AsyncSession, changes: dict[str, bool], updated_by: str) -> dict[str, bool]:
    global _cache
    row = (await session.execute(select(AppSetting).where(AppSetting.key == SETTING_KEY))).scalar_one_or_none()
    flags = _merge(row.value if row else None)
    flags.update({k: bool(v) for k, v in changes.items() if k in KEYS})
    if row is None:
        session.add(AppSetting(key=SETTING_KEY, value=flags, updated_by=updated_by))
    else:
        row.value = flags
        row.updated_by = updated_by
    await session.commit()
    _cache = None
    return flags


def is_super_admin(principal) -> bool:
    """A DH FleetView administrator; if SUPER_ADMIN_EMAILS is set, only those accounts."""
    if principal is None or not principal.is_manager or not principal.administrator:
        return False
    allowed = [e.strip().lower() for e in (settings.super_admin_emails or "").split(",") if e.strip()]
    return not allowed or (principal.email or "").lower() in allowed

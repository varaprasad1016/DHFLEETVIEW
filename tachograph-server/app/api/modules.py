"""Module switches API.

GET  /api/modules  office staff and drivers: which modules are on, and whether
                   the caller may change them (super administrator only).
PUT  /api/modules  super administrator: {"module_key": true|false, ...}.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver_or_manager
from app.database import get_session
from app.services import modules
from app.services.auth import Principal

router = APIRouter(prefix="/api/modules", tags=["modules"])


def _payload(flags: dict[str, bool], principal: Principal) -> dict:
    return {
        "modules": [{"key": k, "label": label, "description": desc, "enabled": flags[k]}
                    for k, label, desc in modules.MODULES],
        "enabled": flags,
        "can_manage": modules.is_super_admin(principal),
    }


@router.get("")
async def get_modules(principal: Principal = Depends(require_driver_or_manager),
                      session: AsyncSession = Depends(get_session)) -> dict:
    return _payload(await modules.get_flags(session), principal)


@router.put("")
async def set_modules(changes: dict[str, bool], principal: Principal = Depends(require_driver_or_manager),
                      session: AsyncSession = Depends(get_session)) -> dict:
    if not modules.is_super_admin(principal):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"error": "not_super_admin",
                                    "message": "Only the super administrator can switch modules on or off."})
    unknown = set(changes) - modules.KEYS
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown modules: {', '.join(sorted(unknown))}")
    flags = await modules.set_flags(session, changes, principal.email or principal.name)
    return _payload(flags, principal)

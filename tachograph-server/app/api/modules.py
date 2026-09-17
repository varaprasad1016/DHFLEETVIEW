"""Module access API.

GET  /api/modules                  the caller's modules (office staff and drivers) and
                                   whether they may manage other users' access.
GET  /api/modules/users/{user_id}  super administrator: a DH FleetView user's modules.
PUT  /api/modules/users/{user_id}  super administrator: {"module_key": true|false, ...}.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver_or_manager, require_manager
from app.database import get_session
from app.services import auth, modules
from app.services.auth import Principal

router = APIRouter(prefix="/api/modules", tags=["modules"])


def _listing(flags: dict[str, bool]) -> list[dict]:
    return [{"key": k, "label": label, "description": desc, "enabled": flags[k]} for k, label, desc in modules.MODULES]


def _require_super(principal: Principal) -> None:
    if not modules.is_super_admin(principal):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"error": "not_super_admin",
                                    "message": "Only the super administrator can change module access."})


@router.get("")
async def my_modules(principal: Principal = Depends(require_driver_or_manager),
                     session: AsyncSession = Depends(get_session)) -> dict:
    flags = await modules.effective_flags(session, principal)
    return {"modules": _listing(flags), "enabled": flags, "can_manage": modules.is_super_admin(principal)}


async def _check_user(principal: Principal, user_id: int) -> dict:
    user = await auth.traccar_get(principal, f"/api/users/{user_id}")
    if not user:
        raise HTTPException(status_code=404, detail="User not found in DH FleetView.")
    return user


@router.get("/users/{user_id}")
async def user_modules(user_id: int, principal: Principal = Depends(require_manager),
                       session: AsyncSession = Depends(get_session)) -> dict:
    _require_super(principal)
    user = await _check_user(principal, user_id)
    full = auth.manager_allowed(user)
    flags, configured = await modules.get_user_flags(session, user_id, default_on=full)
    return {"user_id": user_id, "configured": configured, "full_access": full, "modules": _listing(flags), "enabled": flags}


@router.put("/users/{user_id}")
async def set_user_modules(user_id: int, changes: dict[str, bool],
                           principal: Principal = Depends(require_manager),
                           session: AsyncSession = Depends(get_session)) -> dict:
    _require_super(principal)
    unknown = set(changes) - modules.KEYS
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown modules: {', '.join(sorted(unknown))}")
    user = await _check_user(principal, user_id)
    full = auth.manager_allowed(user)
    flags = await modules.set_user_flags(session, user_id, changes, principal.email or principal.name, default_on=full)
    return {"user_id": user_id, "configured": True, "full_access": full, "modules": _listing(flags), "enabled": flags}

"""Clean Air Zone / ULEZ compliance & charge-exposure API. Licence-gated.
Reads the DVLA-populated vehicle_status rows from the reminders feature.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_license, require_manager
from app.database import get_session
from app.models.vehicle import VehicleStatus
from app.services import caz

router = APIRouter(prefix="/api/caz", tags=["caz"], dependencies=[Depends(require_license), Depends(require_manager)])


@router.get("/exposure")
async def exposure(session: AsyncSession = Depends(get_session)) -> dict:
    vehicles = list((await session.execute(select(VehicleStatus))).scalars().all())
    return caz.exposure(vehicles)


@router.get("/summary")
async def summary(session: AsyncSession = Depends(get_session)) -> dict:
    vehicles = list((await session.execute(select(VehicleStatus))).scalars().all())
    return caz.exposure(vehicles)["summary"]

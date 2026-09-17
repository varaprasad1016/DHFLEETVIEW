"""DVLA/DVSA MOT & tax reminders API. Licence-gated. Monitors a set of
registrations; refreshes each from DVLA VES; flags MOT/tax due-soon and overdue.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_license, require_manager, require_module
from app.database import get_session
from app.models.vehicle import VehicleStatus
from app.services import dvla, reminders

router = APIRouter(prefix="/api/reminders", tags=["reminders"], dependencies=[Depends(require_license), Depends(require_manager), Depends(require_module("reminders"))])


class AddRegsIn(BaseModel):
    regs: list[str]


async def _get(session: AsyncSession, reg: str) -> VehicleStatus | None:
    return (await session.execute(
        select(VehicleStatus).where(VehicleStatus.reg == reg))).scalar_one_or_none()


async def _refresh_one(session: AsyncSession, vs: VehicleStatus) -> None:
    try:
        data = await dvla.lookup(vs.reg)
        for k, v in data.items():
            setattr(vs, k, v)
        vs.check_error = None
    except dvla.DvlaError as e:
        vs.check_error = str(e)
    vs.last_checked = datetime.now(timezone.utc)


@router.get("/config")
async def config() -> dict:
    return {"dvla_configured": dvla.configured(), "due_soon_days": 30}


@router.get("")
async def list_vehicles(session: AsyncSession = Depends(get_session)) -> dict:
    rows = (await session.execute(select(VehicleStatus))).scalars().all()
    views = [reminders.vehicle_view(v) for v in rows]
    order = {"overdue": 0, "due_soon": 1, "unknown": 2, "ok": 3}
    views.sort(key=lambda v: order.get(v["overall"], 9))
    return {"dvla_configured": dvla.configured(), "vehicles": views}


@router.get("/summary")
async def summary(session: AsyncSession = Depends(get_session)) -> dict:
    rows = (await session.execute(select(VehicleStatus))).scalars().all()
    views = [reminders.vehicle_view(v) for v in rows]
    def n(state):
        return sum(1 for v in views if v["overall"] == state)
    return {
        "dvla_configured": dvla.configured(),
        "total": len(views),
        "overdue": n("overdue"), "due_soon": n("due_soon"), "unknown": n("unknown"),
    }


@router.post("/vehicles", status_code=201)
async def add_regs(body: AddRegsIn, session: AsyncSession = Depends(get_session)) -> dict:
    added = 0
    for raw in body.regs:
        reg = reminders.normalize_reg(raw)
        if not reg:
            continue
        if await _get(session, reg) is None:
            session.add(VehicleStatus(reg=reg))
            added += 1
    await session.commit()
    return {"added": added}


@router.delete("/vehicles/{reg}")
async def remove_reg(reg: str, session: AsyncSession = Depends(get_session)) -> dict:
    vs = await _get(session, reminders.normalize_reg(reg))
    if vs is None:
        raise HTTPException(status_code=404, detail="Registration not monitored.")
    await session.delete(vs)
    await session.commit()
    return {"removed": reminders.normalize_reg(reg)}


@router.post("/refresh")
async def refresh(reg: str | None = None, session: AsyncSession = Depends(get_session)) -> dict:
    if not dvla.configured():
        raise HTTPException(status_code=503, detail={
            "error": "dvla_not_configured",
            "message": "Set the DVLA VES API key (dvla_ves_api_key) in the server .env to enable lookups.",
        })
    if reg:
        vs = await _get(session, reminders.normalize_reg(reg))
        if vs is None:
            raise HTTPException(status_code=404, detail="Registration not monitored.")
        targets = [vs]
    else:
        targets = list((await session.execute(select(VehicleStatus))).scalars().all())
    ok = err = 0
    for vs in targets:
        await _refresh_one(session, vs)
        err += 1 if vs.check_error else 0
        ok += 0 if vs.check_error else 1
    await session.commit()
    return {"checked": len(targets), "ok": ok, "errors": err}

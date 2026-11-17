"""Earned Recognition dashboard and targets (licence + office user + module).

GET /api/earned-recognition/dashboard?periods=13
GET /api/earned-recognition/targets
PUT /api/earned-recognition/targets     {"targets": {code: value}, "for_everyone": false}
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Scope, record_scope, require_license, require_manager, require_module
from app.api.maintenance import visible_vehicles
from app.api.tacho import tacho_scope
from app.database import get_session
from app.models.settings import AppSetting
from app.services import earned_recognition as er
from app.services import modules
from app.services.auth import Principal
from app.services.tacho_scope import TachoScope

router = APIRouter(prefix="/api/earned-recognition", tags=["earned recognition"],
                   dependencies=[Depends(require_license), Depends(require_manager), Depends(require_module("earned_recognition"))])


class TargetsIn(BaseModel):
    targets: dict[str, float]
    for_everyone: bool = False


@router.get("/dashboard")
async def dashboard(periods: int = 13, principal: Principal = Depends(require_manager),
                    session: AsyncSession = Depends(get_session), scope: TachoScope = Depends(tacho_scope),
                    shifts_scope: Scope = Depends(record_scope)) -> dict:
    if periods < 1 or periods > 26:
        raise HTTPException(status_code=400, detail="Choose between 1 and 26 periods.")
    targets, source = await er.targets_for(session, principal.user_id)
    vehicles = list(await visible_vehicles(principal))
    data = await er.dashboard(session, scope, shifts_scope, vehicles, targets, count=periods)
    return {**data, "targets_source": source, "can_set_default": modules.is_super_admin(principal)}


@router.get("/inspection-pack.pdf")
async def inspection_pack(start: date, end: date, principal: Principal = Depends(require_manager),
                          session: AsyncSession = Depends(get_session), scope: TachoScope = Depends(tacho_scope),
                          shifts_scope: Scope = Depends(record_scope)) -> Response:
    """Everything an examiner asks for, for your company and the chosen dates, as one PDF."""
    from app.api.driver_records import visible_drivers_by_id
    from app.api.tacho import _latest_company_name
    from app.services import inspection_pack as pack

    if end < start or (end - start).days > 400:
        raise HTTPException(status_code=400, detail="Choose a date range of up to 400 days.")
    from app.services import report_settings

    targets, _ = await er.targets_for(session, principal.user_id)
    hidden, _ = await report_settings.hidden_for(session, principal.user_id)
    company = await _latest_company_name(session, scope) or principal.name
    pdf = await pack.build(session, tacho_scope=scope, record_scope=shifts_scope, vehicles=await visible_vehicles(principal),
                           drivers=await visible_drivers_by_id(principal), start=start, end=end, company=company,
                           generated_by=principal.name, targets=targets, hidden_rules=hidden)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="inspection-pack-{start}-to-{end}.pdf"'})


@router.get("/targets")
async def get_targets(principal: Principal = Depends(require_manager), session: AsyncSession = Depends(get_session)) -> dict:
    targets, source = await er.targets_for(session, principal.user_id)
    return {"source": source, "targets": [{"code": c, "label": spec[1], "unit": spec[2], "direction": spec[3],
                                           "suggested": spec[4], "value": targets[c]} for c, spec in er.KPIS.items()]}


@router.put("/targets")
async def put_targets(body: TargetsIn, principal: Principal = Depends(require_manager),
                      session: AsyncSession = Depends(get_session)) -> dict:
    unknown = set(body.targets) - set(er.KPIS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown measure: {', '.join(sorted(unknown))}")
    for code, value in body.targets.items():
        if value < 0 or (er.KPIS[code][2] == "%" and value > 100):
            raise HTTPException(status_code=400, detail=f"{er.KPIS[code][1]}: target out of range.")
    if body.for_everyone:
        if not modules.is_super_admin(principal):
            raise HTTPException(status_code=403, detail="Only the super administrator can set everyone's targets.")
        key = er.TARGETS_DEFAULT_KEY
    else:
        if principal.user_id is None:
            raise HTTPException(status_code=400, detail="Your account can't store targets.")
        key = f"er_targets:user:{principal.user_id}"
    row = (await session.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
    current, _ = await er.targets_for(session, principal.user_id)
    value = {**current, **body.targets}
    if row is None:
        session.add(AppSetting(key=key, value=value, updated_by=principal.name))
    else:
        row.value, row.updated_by = value, principal.name
    await session.commit()
    return await get_targets(principal, session)

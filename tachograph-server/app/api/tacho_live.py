"""Live tachograph data from FMC650 trackers.

POST /api/tacho-live/ingest   DH FleetView position forwarding (shared key; never licence-gated, so
                              no live data is lost while a licence approval is pending)
GET  /api/tacho-live/board    office live board: who is driving, limits, alerts, mismatches
POST /api/tacho-live/alerts/{id}/acknowledge
"""

from __future__ import annotations

import hmac
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Scope, record_scope, require_license, require_manager, require_module
from app.api.shifts import ACTIVE as ACTIVE_SHIFT
from app.api.tacho import tacho_scope
from app.config import settings
from app.database import get_session
from app.models.driver_auth import DriverAccount, DriverMembership
from app.models.shifts import Shift
from app.models.tacho_live import TachoLiveAlert
from app.services import tacho_live
from app.services.auth import Principal
from app.services.tacho_scope import TachoScope, card_key, reg_key

ingest_router = APIRouter(prefix="/api/tacho-live", tags=["tacho live"])
router = APIRouter(prefix="/api/tacho-live", tags=["tacho live"],
                   dependencies=[Depends(require_license), Depends(require_manager), Depends(require_module("tacho"))])

SHIFT_WITHOUT_CARD_AFTER = timedelta(minutes=15)


@ingest_router.post("/ingest")
async def ingest(payload: dict | list = Body(...), x_tacho_live_key: str | None = Header(default=None),
                 session: AsyncSession = Depends(get_session)) -> dict:
    expected = (settings.tacho_live_key or "").strip()
    if not expected or not x_tacho_live_key or not hmac.compare_digest(x_tacho_live_key.strip(), expected):
        raise HTTPException(status_code=403, detail="Live tacho forwarding key missing or wrong.")
    items = payload if isinstance(payload, list) else [payload]
    results = [await tacho_live.ingest(session, item) for item in items if isinstance(item, dict)]
    return {"received": len(results), "tacho": sum(1 for r in results if r.get("tacho"))}


async def _accounts_by_card(session: AsyncSession) -> dict[str, DriverAccount]:
    rows = (await session.execute(select(DriverAccount).where(DriverAccount.unique_id.is_not(None)))).scalars().all()
    return {card_key(a.unique_id): a for a in rows if len(card_key(a.unique_id)) == 14}


@router.get("/board")
async def board(session: AsyncSession = Depends(get_session),
                scope: TachoScope = Depends(tacho_scope),
                shift_scope: Scope = Depends(record_scope)) -> dict:
    now = datetime.now(timezone.utc)
    accounts = await _accounts_by_card(session)
    visible_names = {card_key(d.get("uniqueId")): d.get("name") for d in scope.drivers if d.get("uniqueId")}

    # Active app shifts this user can see, by driver login.
    shifts = (await session.execute(
        select(Shift).where(shift_scope.condition(Shift), Shift.status.in_(ACTIVE_SHIFT))
    )).scalars().all()
    memberships = dict((await session.execute(
        select(DriverMembership.traccar_driver_id, DriverMembership.account_id))).all())
    account_by_id = {a.id: a for a in accounts.values()}

    def shift_card(shift: Shift) -> str | None:
        account = account_by_id.get(memberships.get(shift.traccar_driver_id))
        if account is None:
            account = next((a for a in accounts.values() if a.name.lower() == (shift.driver_name or "").lower()), None)
        return card_key(account.unique_id) if account else None

    active_by_card: dict[str, Shift] = {}
    for shift in shifts:
        key = shift_card(shift)
        if key:
            active_by_card.setdefault(key, shift)

    rows, seen_cards = [], set()
    for status in await tacho_live.fresh_statuses(session, now):
        if not scope.allows_live(status.card_number, status.vehicle_reg, status.device_uid):
            continue
        view = tacho_live.status_view(status, now)
        key = card_key(status.card_number) if status.card_number else None
        issues = []
        if status.no_card_driving:
            issues.append({"code": "no_card_driving", "level": "bad", "label": "Driving without a driver card"})
        if key:
            if status.card_present:
                seen_cards.add(key)
            account = accounts.get(key)
            view["driver_name"] = visible_names.get(key) or (account.name if account else None) or status.card_holder
            view["driver_login"] = account is not None
            shift = active_by_card.get(key)
            view["shift"] = {"id": str(shift.id), "vehicle_reg": shift.vehicle_reg,
                             "clocked_in_at": shift.clocked_in_at.isoformat()} if shift else None
            if account is None:
                issues.append({"code": "unknown_card", "level": "warn",
                               "label": "Card isn't linked to a driver (set their identifier to this card number)"})
            elif status.working_state in ("drive", "work") and shift is None and not view["stale"]:
                issues.append({"code": "no_shift", "level": "warn", "label": "Working on the tachograph but no shift started in the app"})
            if shift and shift.vehicle_reg and status.vehicle_reg and reg_key(shift.vehicle_reg) != reg_key(status.vehicle_reg):
                issues.append({"code": "other_vehicle", "level": "warn",
                               "label": f"Card is in {status.vehicle_reg}, but the app shift is for {shift.vehicle_reg}"})
        else:
            view["driver_name"] = None
            view["driver_login"] = False
            view["shift"] = None
        if view["warning"]:
            issues.append({"code": f"time_state_{view['warning']['code']}", "level": view["warning"]["level"],
                           "label": view["warning"]["label"]})
        view["issues"] = issues
        rows.append(view)

    # App shifts running for a while with no card in any tracked vehicle.
    tracked = bool(rows)
    no_card_shifts = []
    for shift in shifts:
        key = shift_card(shift)
        if tracked and key and key not in seen_cards and now - shift.clocked_in_at > SHIFT_WITHOUT_CARD_AFTER:
            no_card_shifts.append({"shift_id": str(shift.id), "driver_name": shift.driver_name,
                                   "vehicle_reg": shift.vehicle_reg, "clocked_in_at": shift.clocked_in_at.isoformat()})

    alerts = (await session.execute(
        select(TachoLiveAlert).where(TachoLiveAlert.created_at >= now - timedelta(days=7),
                                     TachoLiveAlert.acknowledged_at.is_(None))
        .order_by(TachoLiveAlert.started_at.desc()).limit(200)
    )).scalars().all()
    alert_rows = [{
        "id": str(a.id), "kind": a.kind, "title": a.title, "vehicle_reg": a.vehicle_reg,
        "started_at": a.started_at.isoformat(), "ended_at": a.ended_at.isoformat() if a.ended_at else None,
        "ongoing": a.kind == "no_card_driving" and a.ended_at is None,
    } for a in alerts if scope.allows_live(a.card_number, a.vehicle_reg, a.device_uid)]

    download_mismatches = []
    for key in sorted({card_key(r["card_number"]) for r in rows if r["card_number"]}):
        for day in await tacho_live.mismatches(session, key, now=now):
            download_mismatches.append({"driver_name": visible_names.get(key) or (accounts[key].name if key in accounts else None),
                                        "card_ending": key[-4:], **day})

    return {
        "generated_at": now.isoformat(),
        "vehicles": rows,
        "alerts": alert_rows,
        "shifts_without_card": no_card_shifts,
        "download_mismatches": download_mismatches,
        "summary": {
            "driving": sum(1 for r in rows if r["activity"] == "drive" and not r["stale"]),
            "working": sum(1 for r in rows if r["activity"] in ("work", "available") and not r["stale"]),
            "resting": sum(1 for r in rows if r["activity"] == "rest" and not r["stale"]),
            "warnings": sum(1 for r in rows if r["issues"]),
            "alerts": len(alert_rows),
        },
    }


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge(alert_id: uuid.UUID, principal: Principal = Depends(require_manager),
                      session: AsyncSession = Depends(get_session),
                      scope: TachoScope = Depends(tacho_scope)) -> dict:
    alert = await session.get(TachoLiveAlert, alert_id)
    if alert is None or not scope.allows_live(alert.card_number, alert.vehicle_reg, alert.device_uid):
        raise HTTPException(status_code=404, detail="Alert not found.")
    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.acknowledged_by = principal.name
    await session.commit()
    return {"id": str(alert.id), "acknowledged": True}

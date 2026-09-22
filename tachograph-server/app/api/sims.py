"""The SIMs in the cameras, and what the network says about them.

A camera that will not come online is nearly always its SIM: not activated, or
barred, or out of data. That answer lives in the SIM provider's portal, which
meant logging in somewhere else to find it. This brings it alongside the
vehicle it belongs to.

Super administrator only - these are our SIMs across every customer, and
deactivating one takes that vehicle's camera off the air.

GET    /api/sims                  every SIM we know of, fitted or in stock
POST   /api/sims/import           take a SIM list exported from the portal
POST   /api/sims/{iccid}/assign   put a SIM in a vehicle, or take it out
POST   /api/sims/status           ask the network about them, live
POST   /api/sims/{iccid}/enable   turn a SIM on or off
POST   /api/sims/{iccid}/limit    raise the level a SIM is cut off at
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_manager
from app.database import get_session
from app.models.sim import SimCard
from app.services import auth, caburn, modules, sim_import
from app.services.auth import Principal

logger = logging.getLogger("tacho.sims")

router = APIRouter(prefix="/api/sims", tags=["sims"])

# Asked of the network at once. Their API is not rate limited, but a fleet's
# worth of sockets at the same moment helps nobody.
AT_ONCE = 6


# At this much of its cut-off a SIM is worth acting on: the month still has
# time to run, and a camera that hits the limit simply goes dark.
NEAR_CUTOFF = 0.75


def _headroom(card: SimCard | None) -> dict:
    """What the last import said about a SIM's data, and how close it is."""
    if card is None:
        return {}
    used, limit = card.data_mb, card.limit_mb
    share = (used / limit) if used is not None and limit else None
    return {
        "used_mb": used, "warning_mb": card.warning_mb, "limit_mb": limit,
        "share_used": round(share, 3) if share is not None else None,
        "near_cutoff": bool(share is not None and share >= NEAR_CUTOFF),
        "over_warning": bool(used is not None and card.warning_mb and used >= card.warning_mb),
        "group": card.group,
    }


def _require_super(principal: Principal) -> None:
    if not modules.is_super_admin(principal):
        raise HTTPException(status_code=403, detail="Only a super administrator can see SIMs.")


# A vehicle can carry two units, each with its own SIM: the camera and a
# separate tracker. They are listed as two SIMs against the one registration,
# because that is what they are - one can be dead while the other is fine.
UNITS = (
    {"fitted": "camera", "iccid": "cmsv9Iccid", "mobile": "cmsv9Mobile", "sim_no": "cmsv9Sim"},
    {"fitted": "tracker", "iccid": "trackerIccid", "mobile": "trackerMobile", "sim_no": "trackerSim"},
)


def _sims_of(device: dict) -> list[dict]:
    """Every SIM in one vehicle. Empty if we hold nothing about any of them."""
    attributes = device.get("attributes") or {}
    sims = []
    for unit in UNITS:
        iccid = str(attributes.get(unit["iccid"]) or "").strip()
        number = str(attributes.get(unit["mobile"]) or "").strip()
        if unit["fitted"] == "camera" and not number:
            # The camera's SIM is what a device's phone number has always meant.
            number = str(device.get("phone") or "").strip()
        if not (iccid or number):
            continue
        sims.append({
            "iccid": iccid or None,
            "msisdn": number or None,
            "sim_no": str(attributes.get(unit["sim_no"]) or "").strip() or None,
            "fitted": unit["fitted"],
            "vehicle": device.get("name"),
            "device_id": device.get("id"),
            "camera_id": attributes.get("cmsv9DeviceId"),
        })
    return sims


@router.get("")
async def list_sims(principal: Principal = Depends(require_manager),
                    session: AsyncSession = Depends(get_session)):
    """Every SIM we know of, from the vehicles it is fitted to.

    Deliberately does not call the network: the list has to appear at once, and
    a fleet's worth of live queries takes seconds. Asking the network is a
    separate step the operator chooses.
    """
    _require_super(principal)
    devices = await auth.traccar_get(principal, "/api/devices") or []
    sims = [sim for device in devices for sim in _sims_of(device)]
    sims.sort(key=lambda s: ((s["vehicle"] or "").upper(), s["fitted"]))
    # Stock: SIMs imported from the portal that are not in a vehicle yet.
    fitted = {sim["iccid"] for sim in sims if sim["iccid"]}
    held = (await session.execute(
        select(SimCard).order_by(SimCard.msisdn, SimCard.iccid))).scalars().all()
    by_iccid = {card.iccid: card for card in held}
    by_number = {card.msisdn: card for card in held if card.msisdn}
    for sim in sims:
        sim.update(_headroom(by_iccid.get(sim["iccid"]) or by_number.get(sim["msisdn"])))
    spare = [{"iccid": card.iccid, "msisdn": card.msisdn, "status": card.status,
              "network": card.network, "imei": card.imei, **_headroom(card)}
             for card in held if card.iccid not in fitted and not card.device_id]

    return {
        "sims": sims,
        "spare": spare,
        "vehicles": sorted(({"id": device.get("id"), "name": device.get("name")}
                            for device in devices),
                           key=lambda device: (device["name"] or "").upper()),
        "without_sim": sorted(device.get("name") for device in devices if not _sims_of(device)),
        "portal_ready": caburn.configured(),
        "near_cutoff": sorted(
            ({"iccid": card.iccid, "msisdn": card.msisdn, "vehicle": card.vehicle,
              **_headroom(card)}
             for card in held if _headroom(card).get("near_cutoff")),
            key=lambda sim: -(sim.get("share_used") or 0)),
        "imported_at": max((card.imported_at.isoformat() for card in held
                            if card.imported_at), default=None),
    }


@router.post("/{iccid}/limit")
async def raise_limit(iccid: str, body: dict = Body(default={}),
                      principal: Principal = Depends(require_manager),
                      session: AsyncSession = Depends(get_session)):
    """Raise the data level at which this SIM is cut off.

    Reaching the limit disables the SIM's traffic, so a camera on a busy month
    simply stops. Raising it is what topping up means for these SIMs - their
    own credit top-up call is for Manx Telecom SIMs only, and ours are EE.

    With no level given, it goes to the next one up from where it is.
    """
    _require_super(principal)
    card = (await session.execute(
        select(SimCard).where(SimCard.iccid == iccid))).scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="That SIM is not in the imported list.")

    wanted = body.get("limit_mb")
    limit = float(wanted) if wanted else caburn.next_step_above(card.limit_mb or 0)
    if card.limit_mb and limit <= card.limit_mb:
        raise HTTPException(
            status_code=400,
            detail=f"That SIM is already cut off at {card.limit_mb:g} MB. "
                   "A new level has to be higher.")

    # Keep the warning proportionate to the new cut-off rather than leaving it
    # where it was, or it fires immediately and means nothing.
    warning = body.get("warning_mb")
    warning = float(warning) if warning else caburn.step_at_least(limit * 0.5)

    try:
        async with httpx.AsyncClient() as client:
            applied = await caburn.set_usage_levels(client, iccid=iccid,
                                                    warning=warning, limit=limit)
    except caburn.CaburnError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    card.limit_mb = applied.get("limit", limit)
    card.warning_mb = applied.get("warning", warning)
    await session.commit()

    logger.info("%s raised SIM %s to a %s MB cut-off", principal.email, iccid, card.limit_mb)
    return {"iccid": iccid, "vehicle": card.vehicle, "limit_mb": card.limit_mb,
            "warning_mb": card.warning_mb, "used_mb": card.data_mb}


@router.post("/import")
async def import_sims(file: UploadFile = File(...),
                      principal: Principal = Depends(require_manager),
                      session: AsyncSession = Depends(get_session)):
    """Take a SIM list exported from the portal.

    Their API answers about one SIM at a time and cannot list an account's
    SIMs, so the stock is imported. A SIM already known is updated rather than
    duplicated, and one already in a vehicle stays where it is.
    """
    _require_super(principal)
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="That file is too large. 5 MB is the limit.")

    try:
        read = sim_import.read(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not read["sims"]:
        raise HTTPException(
            status_code=400,
            detail="No SIMs could be read from that file. It needs a column of ICCIDs - "
                   "the long numbers starting 89.")

    known = {card.iccid: card for card in (await session.execute(
        select(SimCard).where(SimCard.iccid.in_([sim["iccid"] for sim in read["sims"]]))
    )).scalars().all()}

    added, updated = 0, 0
    for found in read["sims"]:
        card = known.get(found["iccid"])
        if card is None:
            session.add(SimCard(**found))
            added += 1
            continue
        for field, value in found.items():
            if field != "iccid" and value not in (None, ""):
                setattr(card, field, value)
        updated += 1
    await session.commit()

    logger.info("%s imported %s SIMs (%s new)", principal.email, len(read["sims"]), added)
    return {"added": added, "updated": updated, "columns": read["columns"],
            "skipped": read["skipped"][:20], "skipped_total": len(read["skipped"])}


@router.post("/{iccid}/assign")
async def assign(iccid: str, body: dict = Body(...),
                 principal: Principal = Depends(require_manager),
                 session: AsyncSession = Depends(get_session)):
    """Put a SIM in a vehicle as its camera's or its tracker's, or take it out.

    The SIM's details are written onto the vehicle, which is where the rest of
    the platform looks for them, and recorded here so the stock list knows the
    SIM is no longer spare.
    """
    _require_super(principal)
    device_id = body.get("device_id")
    fitted = str(body.get("fitted") or "camera").lower()
    if fitted not in ("camera", "tracker"):
        raise HTTPException(status_code=400, detail="A SIM goes in a camera or a tracker.")

    card = (await session.execute(
        select(SimCard).where(SimCard.iccid == iccid))).scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="That SIM is not in the imported list.")

    if device_id in (None, ""):
        # Taking it out of a vehicle. The SIM stays in stock.
        card.device_id = card.vehicle = card.fitted = None
        card.assigned_at = card.assigned_by = None
        await session.commit()
        return {"iccid": iccid, "vehicle": None}

    device = await auth.traccar_get(principal, f"/api/devices/{int(device_id)}")
    if device is None:
        raise HTTPException(status_code=404, detail="There is no such vehicle.")

    unit = next(u for u in UNITS if u["fitted"] == fitted)
    attributes = dict(device.get("attributes") or {})
    attributes[unit["iccid"]] = iccid
    if card.msisdn:
        attributes[unit["mobile"]] = card.msisdn
    device["attributes"] = attributes
    if fitted == "camera" and card.msisdn:
        device["phone"] = card.msisdn

    try:
        await auth.traccar_send(principal, "PUT", f"/api/devices/{int(device_id)}", device)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400,
                            detail=f"The vehicle could not be updated: {exc}") from exc

    card.device_id = int(device_id)
    card.vehicle = device.get("name")
    card.fitted = fitted
    card.assigned_at = datetime.now(timezone.utc)
    card.assigned_by = principal.email
    await session.commit()

    logger.info("%s put SIM %s in %s as its %s", principal.email, iccid, card.vehicle, fitted)
    return {"iccid": iccid, "vehicle": card.vehicle, "fitted": fitted}


async def _ask(client: httpx.AsyncClient, sim: dict, limit: asyncio.Semaphore) -> dict:
    """What the network says about one SIM."""
    answer = {"iccid": sim.get("iccid"), "msisdn": sim.get("msisdn"),
              "vehicle": sim.get("vehicle"), "fitted": sim.get("fitted")}
    async with limit:
        try:
            answer["status"] = await caburn.status(client, iccid=sim.get("iccid"),
                                                   msisdn=sim.get("msisdn"))
        except caburn.CaburnError as exc:
            answer["status"] = None
            answer["problem"] = str(exc)
            return answer
        try:
            answer["usage"] = await caburn.usage(client, iccid=sim.get("iccid"),
                                                 msisdn=sim.get("msisdn"))
        except caburn.CaburnError as exc:
            # A status without usage is still worth having.
            answer["usage"] = None
            answer["usage_problem"] = str(exc)
    return answer


@router.post("/status")
async def live_status(body: dict = Body(default={}),
                      principal: Principal = Depends(require_manager)):
    """Ask the network about these SIMs, now.

    Answers per SIM rather than failing the lot: one SIM the portal will not
    discuss must not hide the fifteen it will.
    """
    _require_super(principal)
    if not caburn.configured():
        raise HTTPException(status_code=400,
                            detail="The SIM portal is not set up on this server yet.")

    wanted = body.get("sims")
    if not wanted:
        devices = await auth.traccar_get(principal, "/api/devices") or []
        wanted = [sim for device in devices for sim in _sims_of(device)]

    limit = asyncio.Semaphore(AT_ONCE)
    async with httpx.AsyncClient() as client:
        answers = await asyncio.gather(*(_ask(client, sim, limit) for sim in wanted))
    return {"sims": list(answers)}


@router.post("/{iccid}/enable")
async def enable(iccid: str, body: dict = Body(default={}),
                 principal: Principal = Depends(require_manager)):
    """Turn a SIM on, or off.

    Off stops all traffic on that SIM, so the camera goes dark until it is
    turned back on. It does not change the tariff, so it does not change what
    the SIM costs.
    """
    _require_super(principal)
    active = bool(body.get("active", True))
    try:
        async with httpx.AsyncClient() as client:
            await caburn.set_status(client, active=active, iccid=iccid)
            settled = await caburn.status(client, iccid=iccid)
    except caburn.CaburnError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info("%s set SIM %s to %s", principal.email, iccid, "active" if active else "de-activated")
    return {"iccid": iccid, "status": settled}

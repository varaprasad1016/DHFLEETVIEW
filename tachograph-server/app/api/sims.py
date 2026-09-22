"""The SIMs in the cameras, and what the network says about them.

A camera that will not come online is nearly always its SIM: not activated, or
barred, or out of data. That answer lives in the SIM provider's portal, which
meant logging in somewhere else to find it. This brings it alongside the
vehicle it belongs to.

Super administrator only - these are our SIMs across every customer, and
deactivating one takes that vehicle's camera off the air.

GET    /api/sims                  every SIM we know of, with its vehicle
POST   /api/sims/status           ask the network about them, live
POST   /api/sims/{iccid}/enable   turn a SIM on or off
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException

from app.api.deps import require_manager
from app.services import auth, caburn, modules
from app.services.auth import Principal

logger = logging.getLogger("tacho.sims")

router = APIRouter(prefix="/api/sims", tags=["sims"])

# Asked of the network at once. Their API is not rate limited, but a fleet's
# worth of sockets at the same moment helps nobody.
AT_ONCE = 6


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
async def list_sims(principal: Principal = Depends(require_manager)):
    """Every SIM we know of, from the vehicles it is fitted to.

    Deliberately does not call the network: the list has to appear at once, and
    a fleet's worth of live queries takes seconds. Asking the network is a
    separate step the operator chooses.
    """
    _require_super(principal)
    devices = await auth.traccar_get(principal, "/api/devices") or []
    sims = [sim for device in devices for sim in _sims_of(device)]
    sims.sort(key=lambda s: ((s["vehicle"] or "").upper(), s["fitted"]))
    return {
        "sims": sims,
        "without_sim": sorted(device.get("name") for device in devices if not _sims_of(device)),
        "portal_ready": caburn.configured(),
    }


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

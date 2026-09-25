"""Running the two listeners a vehicle sends its tachograph file to.

Path A is the Teltonika data protocol: the unit connects, sends positions, and
is asked for a download with a Codec 12 command when one is due. Path B is the
TachoSync protocol, where the unit drives the transfer itself.

Both are off unless switched on. A listener on a public port that nobody has
tested against real hardware is not something to start by default, and the DDD
framing on Path A is reconstructed rather than documented - see the note in
gprs_handler - so the first real unit may need it corrected.

What a unit is allowed to do is decided here; what its file means is not. That
belongs to download_ingest.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal
from app.models.core import Vehicle
from app.services import download_ingest

logger = logging.getLogger("tacho.download")


async def lookup_device(imei: str):
    """The vehicle this unit belongs to, or None to refuse the connection.

    A unit we do not know is turned away rather than quietly accepted: files
    from somebody else's lorry are not ours to keep, and an unknown IMEI is far
    more likely a misconfiguration than a new customer.
    """
    clean = "".join(str(imei or "").split())
    if not clean:
        return None
    async with SessionLocal() as session:
        vehicle = (await session.execute(
            select(Vehicle).where(Vehicle.fmc650_imei == clean))).scalar_one_or_none()
    if vehicle is None:
        logger.warning("a unit with IMEI %s tried to connect; no vehicle has it on record",
                       clean)
        return None
    return {"imei": clean, "vehicle_id": str(vehicle.id),
            "registration": vehicle.registration}


async def get_pending_schedule(device):
    """Whether to ask this unit for a download now.

    Left deliberately simple until a real unit has been through it: a download
    is asked for when the vehicle has none on record inside the vehicle-unit
    window. The scheduling nuances - retry limits, quiet hours, how often to
    ask a unit that keeps failing - are worth settling against hardware rather
    than guessing.
    """
    if not settings.download_request_enabled:
        return None
    registration = device.get("registration")
    if not registration:
        return None

    from datetime import datetime, timedelta, timezone
    from app.models.tacho import TachoFile

    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.vehicle_interval_days)
    async with SessionLocal() as session:
        latest = (await session.execute(
            select(func.max(TachoFile.created_at)).where(
                TachoFile.file_kind == "vehicle_unit",
                TachoFile.vehicle_ref == registration))).scalar_one_or_none()
    if latest is not None and latest > cutoff:
        return None
    return {"reason": f"no vehicle-unit download in {settings.vehicle_interval_days} days",
            "last_download": latest.isoformat() if latest else None}


async def on_positions(device, packet) -> None:
    """Positions arriving on the download channel.

    Tracking already comes through DH FleetView, so these are not stored again;
    they are noted so a silent unit can be told from a chatty one.
    """
    logger.debug("%s sent %d position record(s) on the download channel",
                 device.get("registration") or device.get("imei"), len(packet.records))


async def store_file_path_a(device, filename: str, data: bytes) -> None:
    await download_ingest.ingest(data, filename, imei=device.get("imei"),
                                 vehicle_ref=device.get("registration"),
                                 source="path_a")


async def store_file_path_b(device, metadata, data: bytes) -> None:
    name = getattr(metadata, "filename", None) or f"{device.get('registration') or 'unit'}.ddd"
    await download_ingest.ingest(data, name, imei=device.get("imei"),
                                 vehicle_ref=device.get("registration"),
                                 source="path_b")


def build_servers():
    """The listeners to run, according to what is switched on."""
    from app.protocol.gprs_handler import GprsServer
    from app.protocol.tacho_server import TachoSyncServer

    servers = []
    if settings.gprs_enabled:
        servers.append(("Path A (Teltonika, port %d)" % settings.gprs_port, GprsServer(
            lookup_device=lookup_device,
            get_pending_schedule=get_pending_schedule,
            on_positions=on_positions,
            store_file=store_file_path_a,
            host=settings.download_host, port=settings.gprs_port)))
    if settings.tachosync_enabled:
        servers.append(("Path B (TachoSync, port %d)" % settings.tachosync_port,
                        TachoSyncServer(
                            lookup_device=lookup_device,
                            get_pending_schedule=get_pending_schedule,
                            store_file=store_file_path_b,
                            host=settings.download_host, port=settings.tachosync_port)))
    return servers

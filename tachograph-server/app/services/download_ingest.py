"""What happens when a vehicle sends its own tachograph file in.

The protocol handlers know how to talk to a unit; they do not know what a .ddd
is. This is the piece between them: a file arriving over the air goes through
exactly the same steps as one somebody uploads by hand - archived as it came,
parsed, its activity spans stored, the rules engine run over it, and the
operating company read off it - so a remote download and a manual upload
produce identical records and neither is a second-class citizen.

Nothing here decides whether a download was due or which unit is allowed to
talk to us; the handlers do that. This only deals with the file.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models.core import Vehicle
from app.models.tacho import TachoFile
from app.services import archive

logger = logging.getLogger("tacho.download")


def looks_like_driver_card(data: bytes, filename: str = "") -> bool:
    """Whether this is a driver card rather than a vehicle unit.

    A remote download does not always say which it is, and the two need
    different handling, so it is decided from the file rather than trusted from
    the name. The name is only consulted when the content is unreadable.
    """
    from app.services import ddd_go, ddd_parser

    for reader in (ddd_go.parse_driver_card, ddd_parser.parse_driver_card):
        try:
            reader(data)
            return True
        except Exception:                                   # noqa: BLE001
            continue
    lowered = filename.lower()
    return "card" in lowered or lowered.startswith("c_")


async def ingest(data: bytes, filename: str, *, imei: str | None = None,
                 vehicle_ref: str | None = None, source: str = "download") -> dict:
    """Archive a file that arrived from a vehicle, and put it through the mill.

    Runs in its own session: the protocol handlers are long-lived connections
    and must not hold a database session open between downloads.
    """
    # Imported here: the ingest steps live with the endpoint that has always
    # served them, and importing eagerly would have a service depend on the API
    # layer at start-up.
    from app.api.tacho import (_account_company, _parse_driver_card,
                               _persist_activities, _persist_infringements)
    from app.services import ddd_go, operators
    from app.services.tacho_rules import analyse

    stored = archive.store(filename, data)
    result: dict = {"filename": filename, "sha256": stored["sha256"],
                    "size_bytes": stored["size_bytes"], "source": source}

    async with SessionLocal() as session:
        # Already have this exact file? A unit that resends after a dropped
        # connection must not create a second copy of the same download.
        existing = (await session.execute(
            select(TachoFile).where(TachoFile.sha256 == stored["sha256"]))).scalar_one_or_none()
        if existing is not None:
            logger.info("%s was already archived (%s); nothing re-read",
                        filename, existing.file_kind)
            return {**result, "duplicate": True, "file_id": str(existing.id)}

        company = await _account_company(session)
        company_id = company.id if company else None
        is_card = looks_like_driver_card(data, filename)

        tf = TachoFile(
            filename=filename, file_kind="driver_card" if is_card else "vehicle_unit",
            storage_path=stored["storage_path"], sha256=stored["sha256"],
            size_bytes=stored["size_bytes"], retain_until=stored["retain_until"],
            company_id=company_id, vehicle_ref=vehicle_ref, parsed=False,
            created_at=datetime.now(timezone.utc))
        session.add(tf)
        await session.flush()

        try:
            if is_card:
                parsed, parser = _parse_driver_card(data)
                tf.driver_ref = parsed.get("driver_ref")
                tf.card_number = parsed.get("card_number")
                tf.parsed = True
                await _persist_activities(session, parsed, tf.id, company_id,
                                          driver_ref=tf.driver_ref)
                found = analyse(parsed["activities"], parsed.get("places"),
                                parsed.get("card_gaps"))
                added = await _persist_infringements(
                    session, tf.driver_ref or "unknown", found, tf.id, company_id)
                result.update(file_kind="driver_card", parser=parser,
                              driver_ref=tf.driver_ref, days=parsed.get("days"),
                              infringements=added)
            else:
                from app.services import ddd_parser
                try:
                    tf.company_name = operators.clean_name(
                        ddd_parser.parse_vehicle_unit_company(data))
                except Exception:                           # noqa: BLE001
                    tf.company_name = None
                operator = await operators.resolve(session, tf.company_name)
                if operator is not None:
                    tf.operator_id = operator.id

                parsed = ddd_go.parse_vehicle_unit(data)
                tf.parsed = True
                reg = "".join((parsed.get("vehicle_ref") or "").upper().split())
                vehicle = None
                if reg and company_id is not None:
                    vehicle = (await session.execute(select(Vehicle).where(
                        Vehicle.company_id == company_id,
                        Vehicle.registration == reg))).scalar_one_or_none()
                    if vehicle is None:
                        vehicle = Vehicle(company_id=company_id, registration=reg,
                                          vin=parsed.get("vehicle_vin"),
                                          tachograph_serial=parsed.get("tachograph_serial"))
                        session.add(vehicle)
                        await session.flush()
                        result["vehicle_created"] = True
                if vehicle is not None:
                    tf.vehicle_id = vehicle.id
                    tf.vehicle_ref = vehicle.registration
                    result["operator_on_vehicle"] = await operators.note_vehicle(vehicle, operator)
                await _persist_activities(session, parsed, tf.id, company_id,
                                          vehicle.id if vehicle else None, tf.vehicle_ref,
                                          activity_driver_refs=parsed.get("activity_driver_refs"))
                result.update(file_kind="vehicle_unit", vehicle_ref=tf.vehicle_ref,
                              operator=operator.name if operator else None,
                              days=parsed.get("days"))
        except Exception as exc:                            # noqa: BLE001
            # The file is kept whatever happens. A download we cannot read is
            # still the operator's record and still has to be producible for
            # DVSA; it is flagged for a person rather than thrown away.
            tf.parsed = False
            tf.parse_error = str(exc)[:500]
            result["parse_error"] = str(exc)
            logger.warning("%s arrived but could not be read: %s", filename, exc)

        await session.commit()
        result["file_id"] = str(tf.id)

    logger.info("stored %s from %s (%s)", filename, imei or "a vehicle",
                result.get("file_kind", "unknown"))
    return result

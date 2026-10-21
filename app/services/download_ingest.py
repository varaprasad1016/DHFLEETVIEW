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
import re
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
    from app.services import ddd_go, ddd_parser, ddd_traconiq

    for reader in (ddd_traconiq.parse_driver_card, ddd_go.parse_driver_card,
                   ddd_parser.parse_driver_card):
        try:
            reader(data)
            return True
        except Exception:                                   # noqa: BLE001
            continue
    lowered = filename.lower()
    return "card" in lowered or lowered.startswith("c_")


# TachoSync and the units name a download after the vehicle:
# M_20261021_1704_PJ19FBK_YV2RTY0C2KA850352.DDD. When the file itself cannot be
# read that name is the only registration there is, and a file nobody can
# attach to a vehicle is a file nobody can find again.
_NAME_REG = re.compile(r"_([A-Z]{2}\d{2}[A-Z]{3}|[A-Z]\d{1,3}[A-Z]{3}|[A-Z]{3}\d{1,4})_")


def registration_in(filename: str) -> str | None:
    match = _NAME_REG.search((filename or "").upper().replace(" ", ""))
    return match.group(1) if match else None


async def ingest(data: bytes, filename: str, *, imei: str | None = None,
                 vehicle_ref: str | None = None, source: str = "download",
                 company_id=None) -> dict:
    """Archive a file that arrived from a vehicle, and put it through the mill.

    Runs in its own session: the protocol handlers are long-lived connections
    and must not hold a database session open between downloads.
    """
    # Imported here: the ingest steps live with the endpoint that has always
    # served them, and importing eagerly would have a service depend on the API
    # layer at start-up.
    from app.api.tacho import _account_company

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

        # The caller says whose file this is when it knows - a fetch made with
        # a customer's own TachoSync key knows exactly - and only falls back to
        # the deployment's single tenant when it does not.
        if company_id is None:
            company = await _account_company(session)
            company_id = company.id if company else None
        is_card = looks_like_driver_card(data, filename)

        tf = TachoFile(
            filename=filename, file_kind="driver_card" if is_card else "vehicle_unit",
            storage_path=stored["storage_path"], sha256=stored["sha256"],
            size_bytes=stored["size_bytes"], retain_until=stored["retain_until"],
            company_id=company_id, vehicle_ref=vehicle_ref, parsed=False,
            source=(source or "")[:12], created_at=datetime.now(timezone.utc))
        session.add(tf)
        await session.flush()

        await _read_into(session, tf, data, company_id=company_id,
                         vehicle_ref=vehicle_ref, result=result)

        await session.commit()
        result["file_id"] = str(tf.id)

    logger.info("stored %s from %s (%s)", filename, imei or "a vehicle",
                result.get("file_kind", "unknown"))
    return result


async def _read_into(session, tf, data: bytes, *, company_id, vehicle_ref: str | None,
                     result: dict, run_analysis: bool = True) -> None:
    """Parse `data` into an archived file row, with its activities and findings.

    Shared by a file that has just arrived and by a re-read of one an older
    parser could not manage. It never raises for an unreadable file: the row is
    flagged instead, because a download nobody can parse is still the
    operator's record and still has to be producible for DVSA.
    """
    from app.api.tacho import (_parse_driver_card, _persist_activities,
                               analyse_card_records, analyse_driver,
                               parse_vehicle_unit)
    from app.services import operators

    filename = tf.filename
    is_card = tf.file_kind == "driver_card"


    try:
        if is_card:
            parsed, parser = _parse_driver_card(data)
            tf.driver_ref = parsed.get("driver_ref")
            tf.card_number = parsed.get("card_number")
            # The expiry comes off the card itself, and the driver records page
            # counts on it for card-renewal warnings. The hand-upload path has
            # always kept it; a file fetched automatically must not quietly
            # know less than one somebody dragged in.
            tf.card_expiry = parsed.get("card_expiry") or tf.card_expiry
            tf.parsed = True
            tf.parse_error = None
            await _persist_activities(session, parsed, tf.id, company_id,
                                      driver_ref=tf.driver_ref)

            # Two passes, because they answer different questions from
            # different evidence: the hours from everything known about this
            # driver, and the country entries and card withdrawals from this
            # card, which is the only thing that records them. The card's own
            # pass runs now whatever the caller asked, because it depends on
            # nothing but this file and the places are not kept anywhere else.
            who = tf.driver_ref or "unknown"
            added = await analyse_card_records(session, who, parsed, tf.id, company_id)
            if run_analysis:
                added += await analyse_driver(session, who, company_id, tf.id)

            result.update(file_kind="driver_card", parser=parser,
                          driver_ref=tf.driver_ref, days=parsed.get("days"),
                          drivers=[tf.driver_ref] if tf.driver_ref else [],
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

            parsed = parse_vehicle_unit(data)
            tf.parsed = True
            tf.parse_error = None
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

            # Then judge each driver the unit recorded, over their whole
            # timeline rather than just this file. A vehicle unit names the
            # drivers who used it; spans with nobody in the slot belong to no
            # driver and are not anybody's hours.
            added = 0
            if run_analysis:
                for who in parsed.get("drivers") or []:
                    added += await analyse_driver(session, who, company_id, tf.id)

            result.update(file_kind="vehicle_unit", vehicle_ref=tf.vehicle_ref,
                          operator=operator.name if operator else None,
                          parser=parsed.get("parser"),
                          generation=parsed.get("generation"),
                          drivers=parsed.get("drivers"),
                          infringements=added,
                          days=parsed.get("days"))
    except Exception as exc:                            # noqa: BLE001
        # The file is kept whatever happens. A download we cannot read is
        # still the operator's record and still has to be producible for
        # DVSA; it is flagged for a person rather than thrown away.
        tf.parsed = False
        tf.parse_error = str(exc)[:500]
        result["parse_error"] = str(exc)
        logger.warning("%s could not be read: %s", filename, exc)

    # Attach it to its vehicle whatever happened above. A download that
    # would not parse still belongs to a lorry, and the registration is in
    # the file name even when it is not readable inside the file.
    if not tf.vehicle_ref and tf.file_kind == "vehicle_unit":
        tf.vehicle_ref = vehicle_ref or registration_in(filename)
    if tf.vehicle_ref and tf.vehicle_id is None and company_id is not None:
        reg = "".join(tf.vehicle_ref.upper().split())
        tf.vehicle_ref = reg
        vehicle = (await session.execute(select(Vehicle).where(
            Vehicle.company_id == company_id,
            Vehicle.registration == reg))).scalar_one_or_none()
        if vehicle is None:
            vehicle = Vehicle(company_id=company_id, registration=reg)
            session.add(vehicle)
            await session.flush()
            result["vehicle_created"] = True
        tf.vehicle_id = vehicle.id
        result["vehicle_ref"] = reg


async def reparse(*, only_failed: bool = True, limit: int = 500) -> list[dict]:
    """Read archived files again with the parsers installed today.

    A download no reader of the day could manage is kept rather than thrown
    away, exactly so that a better reader arriving later still has the file to
    read. This is what makes such an upgrade reach the files already in the
    archive instead of only the next ones to arrive.

    Re-reading is safe to repeat: a file's activity spans are replaced rather
    than added to, so running this twice leaves the same record as running it
    once.
    """
    from app.api.tacho import analyse_driver

    done: list[dict] = []
    drivers: set[tuple[str, object, object]] = set()
    async with SessionLocal() as session:
        query = select(TachoFile).order_by(TachoFile.created_at)
        if only_failed:
            query = query.where(TachoFile.parsed.is_(False))
        files = (await session.execute(query.limit(limit))).scalars().all()

        for tf in files:
            result: dict = {"filename": tf.filename, "file_id": str(tf.id),
                            "was": tf.parse_error}
            try:
                with open(tf.storage_path, "rb") as handle:
                    data = handle.read()
            except OSError as exc:
                result["error"] = f"archived file could not be read: {exc}"
                done.append(result)
                continue

            # Hold the analysis back until every file has been re-read.
            # Judging a driver while half the archive is still the old
            # reading measures them against a timeline that is part new and
            # part stale, and records findings from it.
            await _read_into(session, tf, data, company_id=tf.company_id,
                             vehicle_ref=tf.vehicle_ref, result=result,
                             run_analysis=False)
            result["parsed"] = tf.parsed
            done.append(result)
            for who in result.get("drivers") or []:
                drivers.add((who, tf.company_id, tf.id))

        await session.commit()

        judged = 0
        for who, company_id, file_id in sorted(drivers, key=lambda d: str(d[0])):
            judged += await analyse_driver(session, who, company_id, file_id)
        await session.commit()

    readable = sum(1 for entry in done if entry.get("parsed"))
    logger.info("re-read %d archived file(s); %d now parse, %d finding(s) from %d driver(s)",
                len(done), readable, judged, len(drivers))
    return done

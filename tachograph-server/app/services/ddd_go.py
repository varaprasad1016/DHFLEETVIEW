"""Driver-card parsing via the `tachograph` CLI from way-platform/tachograph-go.

That project is an MIT-licensed Go implementation of Regulation (EU) 2016/799,
kept current with the specification, and it covers ground our own reader does
not: second-generation and smart tachograph layouts, the cyclic buffers, and
cryptographic verification of the signatures on each block.

It runs as a separate process and returns JSON, which this module maps onto the
same dictionary the built-in parser returns, so the rules engine and the report
never learn which reader produced their input. If the binary is not configured
or fails, the caller falls back to the built-in reader for driver cards only.
Vehicle-unit files are parsed by tachograph-go and are never sent to the
card-only fallback.

Note on licences: this is MIT, so it imposes nothing on the code around it. The
better known kyburz/traconiq `tachoparser` is AGPL-3.0, which for a hosted
service reaches much further, and is deliberately not used here.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import settings
from app.services.tacho_rules import Activity, CardGap, PlaceEntry

log = logging.getLogger(__name__)

_ACTIVITY = {
    "BREAK_REST": "rest",
    "AVAILABILITY": "available",
    "WORK": "work",
    "DRIVING": "drive",
}


def _activity_kind(value) -> str | None:
    """Map tachograph-go's enum name or numeric enum value to a kind."""
    if isinstance(value, int):
        return {2: "rest", 3: "available", 4: "work", 5: "drive"}.get(value)
    if not isinstance(value, str):
        return None
    name = value.upper()
    if name in _ACTIVITY:
        return _ACTIVITY[name]
    for suffix, kind in _ACTIVITY.items():
        if name.endswith("_" + suffix):
            return kind
    return None
# Values that mean the driver never actually entered a country.
_NO_COUNTRY = {"", "NO_INFORMATION", "UNKNOWN", "RESERVED", "UNSPECIFIED",
               "NATION_UNSPECIFIED", "NATION_NO_INFORMATION"}
_ODOMETER_UNSET = 0xFFFFFF


class GoParserUnavailable(RuntimeError):
    """The CLI is not configured, not installed, or not runnable."""


def binary_path() -> str | None:
    """The configured binary, or whatever is on PATH under a known name."""
    configured = (settings.tacho_parser_binary or "").strip()
    if configured:
        path = Path(configured).expanduser()
        # An absolute path must exist; a relative path may be an executable in
        # the current directory, while a bare name is resolved through PATH.
        if path.parent != Path("."):
            return str(path) if path.is_file() else None
        if path.is_file():
            return str(path)
        return shutil.which(configured)
    return shutil.which("tachograph") or shutil.which("dddparser")


def available() -> bool:
    """Whether the optional Go reader can be invoked."""
    return bool(settings.tacho_parser_enabled and binary_path())


def _run(data: bytes) -> dict:
    if not settings.tacho_parser_enabled:
        raise GoParserUnavailable("tachograph-go parser is disabled")
    exe = binary_path()
    if not exe:
        raise GoParserUnavailable("no tachograph CLI configured or on PATH")
    with tempfile.TemporaryDirectory(prefix="ddd-") as tmp:
        card = Path(tmp) / "card.ddd"
        card.write_bytes(data)
        argv = [exe, "parse", str(card)]
        if settings.tacho_parser_authenticate:
            argv.append("--authenticate")
        try:
            proc = subprocess.run(argv, capture_output=True,
                                  timeout=settings.tacho_parser_timeout,
                                  check=False)
        except FileNotFoundError as exc:
            raise GoParserUnavailable(f"tachograph CLI is not runnable: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise GoParserUnavailable(
                f"tachograph CLI timed out after {settings.tacho_parser_timeout}s") from exc
    if proc.returncode != 0:
        raise RuntimeError(
            f"tachograph CLI exited {proc.returncode}: "
            f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
    if not proc.stdout.strip():
        raise RuntimeError("tachograph CLI produced no output")
    try:
        document = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("tachograph CLI returned invalid JSON") from exc
    if not isinstance(document, dict):
        raise RuntimeError("tachograph CLI returned a JSON value, not an object")
    return document


def _time(value) -> datetime | None:
    """Read a protojson Timestamp, ISO string, or protobuf-style timestamp."""
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, dict):
        if value.get("value") is not None:
            return _time(value["value"])
        if value.get("seconds") is not None:
            try:
                parsed = datetime.fromtimestamp(
                    int(value["seconds"]), tz=timezone.utc)
                parsed += timedelta(microseconds=int(value.get("nanos", 0)) // 1000)
            except (TypeError, ValueError, OverflowError):
                return None
        else:
            return None
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _activities(block: dict) -> tuple[list[Activity], list[CardGap]]:
    """Daily records to contiguous spans, plus the periods the card was out."""
    records = []
    for record in block.get("dailyRecords") or []:
        day = _time(record.get("activityRecordDate"))
        if day is None:
            continue
        changes = []
        for change in record.get("activityChangeInfo") or []:
            if change.get("slot") not in (None, "DRIVER_SLOT"):
                continue
            kind = _ACTIVITY.get(change.get("activity"))
            if kind is None:
                continue
            minute = int(change.get("timeOfChangeMinutes") or 0)
            if 0 <= minute <= 1440:
                # `inserted` is the card's own view: false means it was not in a
                # tachograph for that stretch.
                changes.append((minute, kind, not change.get("inserted", True)))
        changes.sort(key=lambda c: c[0])
        if changes:
            records.append((day.replace(hour=0, minute=0, second=0, microsecond=0),
                            changes))
    records.sort(key=lambda r: r[0])

    acts: list[Activity] = []
    out_spans: list[tuple[datetime, datetime]] = []
    for index, (day, changes) in enumerate(records):
        newest = index == len(records) - 1
        for position, (minute, kind, card_out) in enumerate(changes):
            if position + 1 < len(changes):
                end_minute = changes[position + 1][0]
            elif newest:
                # The card was downloaded part way through this day, so the
                # final activity has no recorded end. Running it to midnight
                # would invent hours of work that never happened.
                break
            else:
                end_minute = 1440
            if end_minute <= minute:
                continue
            start = day + timedelta(minutes=minute)
            end = day + timedelta(minutes=end_minute)
            acts.append(Activity(kind, start, end))
            if card_out:
                out_spans.append((start, end))

    gaps: list[CardGap] = []
    for start, end in out_spans:
        if gaps and gaps[-1].end == start:
            gaps[-1] = CardGap(gaps[-1].start, end)
        else:
            gaps.append(CardGap(start, end))
    return acts, gaps


def _places(block: dict) -> list[PlaceEntry]:
    out: list[PlaceEntry] = []
    for record in block.get("records") or []:
        when = _time(record.get("entryTime"))
        if when is None:
            continue
        entry_type = (record.get("entryTypeDailyWorkPeriod") or "").upper()
        country = (record.get("dailyWorkPeriodCountry") or "").upper()
        out.append(PlaceEntry(
            when,
            "end" if entry_type.startswith("END") else "begin",
            country=0,
            country_name="" if country in _NO_COUNTRY else country))
    out.sort(key=lambda p: p.time)
    return out


def _vehicles(block: dict) -> list:
    from app.services.ddd_parser import VehiclePeriod

    out = []
    for record in block.get("records") or []:
        first = _time(record.get("vehicleFirstUse"))
        if first is None:
            continue
        registration = ((record.get("vehicleRegistration") or {})
                        .get("number") or {}).get("value") or ""
        start = record.get("vehicleOdometerBeginKm")
        end = record.get("vehicleOdometerEndKm")
        out.append(VehiclePeriod(
            registration=registration.strip(),
            nation=0,
            first_use=first,
            last_use=_time(record.get("vehicleLastUse")),
            odometer_start=None if start in (None, _ODOMETER_UNSET) else int(start),
            # The newest spell is still open, so its closing odometer is unset.
            odometer_end=None if end in (None, _ODOMETER_UNSET) else int(end)))
    out.sort(key=lambda v: v.first_use)
    return out


def _incidents(events: dict, faults: dict) -> list:
    from app.services.ddd_parser import CardIncident

    out = []
    for kind, block, key in (("event", events, "events"), ("fault", faults, "faults")):
        for record in block.get(key) or []:
            if record.get("valid") is False:
                continue
            start = _time(record.get("eventBeginTime") or record.get("faultBeginTime")
                          or record.get("beginTime"))
            if start is None:
                continue
            name = (record.get("eventType") or record.get("faultType")
                    or record.get("type") or f"{kind} of unknown type")
            registration = ((record.get("eventVehicleRegistration")
                             or record.get("faultVehicleRegistration") or {})
                            .get("number") or {}).get("value") or ""
            out.append(CardIncident(
                kind=kind, code=0,
                name=str(name).replace("_", " ").capitalize(),
                start=start,
                end=_time(record.get("eventEndTime") or record.get("faultEndTime")
                          or record.get("endTime")),
                registration=registration.strip()))
    out.sort(key=lambda e: e.start)
    return out


def _json_value(value):
    """Return a useful value from a protojson scalar wrapper."""
    if isinstance(value, dict):
        return value.get("value")
    return value


def _nested_raw(value: dict, *keys: str):
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _nested_value(value: dict, *keys: str):
    return _json_value(_nested_raw(value, *keys))


def _vehicle_unit_root(document: dict) -> tuple[dict, dict, str]:
    """Return (vehicleUnit, generation variant, generation label) from CLI JSON."""
    root = document.get("vehicleUnit") or document.get("vehicle_unit")
    if not isinstance(root, dict):
        raise ValueError(f"not a vehicle-unit file (file type {document.get('type')!r})")
    variants = (
        ("gen1", "GENERATION_1"),
        ("gen2V1", "GENERATION_2_VERSION_1"),
        ("gen2_v1", "GENERATION_2_VERSION_1"),
        ("gen2V2", "GENERATION_2_VERSION_2"),
        ("gen2_v2", "GENERATION_2_VERSION_2"),
    )
    for key, label in variants:
        variant = root.get(key)
        if isinstance(variant, dict):
            return root, variant, label
    # Keep this tolerant of a future CLI spelling while refusing an empty VU.
    for key, value in root.items():
        if key.lower().startswith("gen") and isinstance(value, dict):
            return root, value, key.upper()
    raise ValueError("vehicle-unit file has no recognised generation data")


def _vu_driver_ref(card: dict) -> str | None:
    holder = card.get("cardHolderName") or card.get("card_holder_name") or {}
    surname = _nested_value(holder, "holderSurname") or _nested_value(holder, "holder_surname") or ""
    first = _nested_value(holder, "holderFirstNames") or _nested_value(holder, "holder_first_names") or ""
    name = " ".join(part.strip() for part in (str(surname), str(first)) if str(part).strip())
    number = card.get("fullCardNumber") or card.get("full_card_number") or {}
    driver = number.get("driverIdentification") or number.get("driver_identification") or {}
    card_number = "".join(str(_nested_value(driver, key) or "") for key in (
        "driverIdentificationNumber", "cardReplacementIndex", "cardRenewalIndex"))
    return name or card_number or None


def _vu_activities(variant: dict) -> tuple[list[Activity], list[str | None]]:
    """Flatten Gen1/Gen2 daily VU records into canonical spans.

    VU files contain activity records for the vehicle, rather than one driver's
    card. A VU card-insertion record is used when available to attach a driver
    reference; spans without a matching insertion remain vehicle-only.
    """
    daily = variant.get("activities") or []
    records = []
    for record in daily:
        day = _time(_nested_raw(record, "dateOfDay") or _nested_raw(record, "date_of_day"))
        if day is None:
            # ProtoJSON uses snake_case for fields emitted by protojson.Format;
            # the camelCase form is accepted as well for fixtures/older CLIs.
            day = _time(record.get("dateOfDay") or record.get("date_of_day"))
        if day is None:
            continue
        changes = []
        for change in record.get("activityChanges") or record.get("activity_changes") or []:
            activity = change.get("activity")
            kind = _activity_kind(activity)
            if kind is None:
                continue
            minute = int(change.get("timeOfChangeMinutes") or change.get("time_of_change_minutes") or 0)
            slot = change.get("slot")
            if isinstance(slot, int) and slot not in (0, 1):
                continue
            if slot not in (None, 0, 1, 2, 3, "DRIVER_SLOT", "CO_DRIVER_SLOT",
                            "CARD_SLOT_DRIVER", "CARD_SLOT_CO_DRIVER", "CARD_SLOT_1",
                            "CARD_SLOT_2") or not 0 <= minute <= 1440:
                continue
            changes.append((minute, kind, not change.get("inserted", True)))
        changes.sort(key=lambda item: item[0])
        if changes:
            records.append((day.replace(hour=0, minute=0, second=0, microsecond=0), changes))
    records.sort(key=lambda item: item[0])

    cards = []
    for record in daily:
        for card in (record.get("cardIwData") or record.get("card_iw_data") or []):
            ref = _vu_driver_ref(card)
            inserted = _time(_nested_raw(card, "cardInsertionTime") or _nested_raw(card, "card_insertion_time") or card.get("cardInsertionTime") or card.get("card_insertion_time"))
            withdrawn = _time(_nested_raw(card, "cardWithdrawalTime") or _nested_raw(card, "card_withdrawal_time") or card.get("cardWithdrawalTime") or card.get("card_withdrawal_time"))
            if ref and inserted:
                cards.append((ref, inserted, withdrawn))

    activities: list[Activity] = []
    refs: list[str | None] = []
    for index, (day, changes) in enumerate(records):
        last_record = index == len(records) - 1
        for position, (minute, kind, card_out) in enumerate(changes):
            end_minute = changes[position + 1][0] if position + 1 < len(changes) else (None if last_record else 1440)
            if end_minute is None or end_minute <= minute:
                continue
            start = day + timedelta(minutes=minute)
            end = day + timedelta(minutes=end_minute)
            activities.append(Activity(kind, start, end))
            ref = next((driver for driver, inserted, withdrawn in cards
                        if end > inserted and (withdrawn is None or start < withdrawn)), None)
            refs.append(ref)
    return activities, refs


def parse_vehicle_unit(data: bytes) -> dict:
    """Parse a VU download with the same tachograph-go CLI used for cards."""
    document = _run(data)
    root, variant, generation = _vehicle_unit_root(document)
    overview = variant.get("overview") or {}
    registration = (_nested_value(overview, "vehicleRegistrationWithNation", "number") or
                    _nested_value(overview, "vehicle_registration_with_nation", "number"))
    if not registration:
        registration = (_nested_value(overview, "vehicleRegistrationIdentification", "number") or
                        _nested_value(overview, "vehicle_registration_identification", "number"))
    vin = (_nested_value(overview, "vehicleIdentificationNumber") or
           _nested_value(overview, "vehicle_identification_number"))

    technical = variant.get("technicalData") or variant.get("technical_data") or []
    tachograph_serial = None
    if technical:
        identification = technical[0].get("vuIdentification") or technical[0].get("vu_identification") or {}
        serial = (_nested_raw(identification, "serialNumber") or
                  _nested_raw(identification, "serial_number"))
        # ExtendedSerialNumber.serialNumber is a protobuf scalar, not a
        # StringValue wrapper, so it is deliberately handled separately from
        # the IA5/StringValue fields above.
        if isinstance(serial, dict):
            tachograph_serial = serial.get("serialNumber", serial.get("serial_number"))
        else:
            tachograph_serial = serial
        if tachograph_serial is not None:
            tachograph_serial = str(tachograph_serial)

    activities, driver_refs = _vu_activities(variant)
    drivers = sorted({ref for ref in driver_refs if ref})
    return {
        "activities": activities,
        "activity_driver_refs": driver_refs,
        "days": len({activity.start.date() for activity in activities}),
        "vehicle_ref": str(registration).strip() if registration else None,
        "vehicle_vin": str(vin).strip() if vin else None,
        "tachograph_serial": tachograph_serial,
        "drivers": drivers,
        "generation": generation,
        "parser": "tachograph-go",
        "file_type": "vehicle_unit",
    }


def parse_driver_card(data: bytes) -> dict:
    """Same contract as the built-in parser: raises ValueError on unusable data."""
    document = _run(data)
    card = document.get("driverCard") or {}
    block = card.get("tachograph") or {}
    if not block:
        raise ValueError(f"not a driver card (file type {document.get('type')!r})")

    acts, gaps = _activities(block.get("driverActivityData") or {})
    if not acts:
        raise ValueError("driver activity block present but no readable records")

    identification = block.get("identification") or {}
    surname = (identification.get("cardHolderSurname") or {}).get("value") or ""
    first_names = (identification.get("cardHolderFirstNames") or {}).get("value") or ""
    driver = identification.get("driverIdentification") or {}
    card_number = "".join(
        str((driver.get(part) or {}).get("value") or "")
        for part in ("driverIdentificationNumber", "cardReplacementIndex",
                     "cardRenewalIndex"))
    name = " ".join(part for part in (surname.strip(), first_names.strip()) if part)

    return {
        "activities": acts,
        "places": _places(block.get("places") or {}),
        "card_gaps": gaps,
        "vehicles": _vehicles(block.get("vehiclesUsed") or {}),
        "incidents": _incidents(block.get("eventsData") or {},
                                block.get("faultsData") or {}),
        "days": len({a.start.date() for a in acts}),
        "card_number": card_number.strip() or None,
        "driver_name": name or None,
        "driver_ref": name or card_number.strip() or None,
        "parser": "tachograph-go",
    }

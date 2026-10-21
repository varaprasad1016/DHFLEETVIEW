"""Driver-card and vehicle-unit parsing via traconiq/tachoparser's `dddparser`.

Why this reader exists
----------------------
The MIT-licensed tachograph-go reader in :mod:`app.services.ddd_go` cannot read
second-generation version 1 vehicle units: it stops at the vehicle registration
identification record with "invalid data length for VehicleRegistrationIdenti-
fication", which is every Continental VU in the fleet downloaded through
TachoSync. tachoparser reads those files completely, including the daily
activity blocks, the card insertion/withdrawal records and the GNSS positions.

Licence, and why this is a subprocess
-------------------------------------
tachoparser is AGPL-3.0. It is invoked here as a standalone executable over
stdin/stdout and nothing from it is imported, linked or vendored into this
application, which keeps our own source outside the copyleft boundary. The
AGPL's network clause still obliges us to offer tachoparser's corresponding
source to anyone interacting with it over a network: the build tree is kept at
``D:\\tools\\tachoparser-src`` and recorded in ``PROVENANCE.txt`` beside the
binary. Treat replacing that binary as a licence-relevant act, not a tidy-up.

Contract
--------
:func:`parse_vehicle_unit` and :func:`parse_driver_card` return exactly the
dictionaries :mod:`app.services.ddd_go` returns, so the rules engine, the
activity store and the reports cannot tell which reader produced their input.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.services.tacho_rules import Activity, CardGap, PlaceEntry

log = logging.getLogger(__name__)

PARSER_NAME = "tachoparser"

# ActivityChangeInfo's two activity bits, as the regulation numbers them.
# tachoparser hands these over already decoded, so these are the raw values
# rather than any library's enum offsets.
_WORK_TYPE = {0: "rest", 1: "available", 2: "work", 3: "drive"}

# NationNumeric values that mean no country was actually entered.
_NO_NATION = {0x00, 0xFD, 0xFE, 0xFF}

# An odometer that was never set reads as all ones.
_ODOMETER_UNSET = 0xFFFFFF

# Blocks come in three flavours, newest first: second-generation version 2,
# second-generation version 1, then first-generation. A file carries whichever
# its tachograph supports, and a V2 unit carries all three.
_GENERATIONS = (
    ("_2_v2", "GENERATION_2_VERSION_2"),
    ("_2", "GENERATION_2_VERSION_1"),
    ("_1", "GENERATION_1"),
)


class TraconiqUnavailable(RuntimeError):
    """The binary is not configured, not installed, or not runnable."""


def binary_path() -> str | None:
    """The configured binary, or whatever is on PATH under a known name."""
    configured = (settings.tacho_traconiq_binary or "").strip()
    if configured:
        return configured if os.path.isfile(configured) else None
    return shutil.which("dddparser") or shutil.which("dddparser.exe")


def available() -> bool:
    return bool(settings.tacho_traconiq_enabled and binary_path())


def _run(data: bytes, kind: str) -> dict:
    """Run the parser over `data` and return its JSON document.

    `kind` is "vu" or "card"; the binary insists on being told which, and
    refuses to guess.
    """
    binary = binary_path()
    if not binary:
        raise TraconiqUnavailable("tachoparser binary is not configured")
    if not data:
        raise ValueError("empty file")

    try:
        done = subprocess.run(
            [binary, f"-{kind}", "-output", "-"],
            input=data, capture_output=True,
            timeout=settings.tacho_traconiq_timeout, check=False)
    except FileNotFoundError as exc:
        raise TraconiqUnavailable(f"tachoparser binary not found: {binary}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"tachoparser timed out after {settings.tacho_traconiq_timeout}s") from exc

    # Everything the parser says about certificates and skipped blocks goes to
    # stderr, including on a wholly successful run, so it is diagnostic only.
    noise = (done.stderr or b"").decode("utf-8", "replace").strip()
    if done.returncode != 0:
        tail = " / ".join(line for line in noise.splitlines()[-3:])
        raise RuntimeError(f"tachoparser exited {done.returncode}: {tail[:400]}")
    if noise:
        log.debug("tachoparser notes: %s", noise[-600:])

    body = (done.stdout or b"").strip()
    if not body:
        raise ValueError("tachoparser produced no output")
    try:
        document = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"tachoparser output was not JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("tachoparser output was not an object")
    return document


def _time(value) -> datetime | None:
    """Read tachoparser's RFC 3339 timestamps, in UTC."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    # A tachograph with a flat backup battery writes year 0, which is not a
    # date anybody should see on a report.
    if parsed.year < 1990:
        return None
    return parsed.astimezone(timezone.utc)


def _records(block, *names) -> list:
    """Pull a record list out of a block under any of `names`.

    Second-generation blocks wrap their lists in a record array
    (``{"records": [...]}``); first-generation blocks hold the list directly.
    Both spellings are accepted so one caller serves both.
    """
    if not isinstance(block, dict):
        return []
    for name in names:
        value = block.get(name)
        if isinstance(value, dict):
            inner = value.get("records")
            if isinstance(inner, list):
                return inner
        elif isinstance(value, list):
            return value
    return []


def _one(block, *names):
    """The single record a record array holds, or None."""
    found = _records(block, *names)
    return found[0] if found else None


def _card_number(card: dict) -> str:
    """The card number out of either card-number spelling."""
    if not isinstance(card, dict):
        return ""
    holder = card.get("full_card_number_and_generation") or card
    number = holder.get("full_card_number") or holder.get("card_identification") or {}
    if isinstance(number, dict):
        return str(number.get("card_number") or "").strip()
    return ""


def _holder_name(card: dict) -> str:
    name = (card or {}).get("card_holder_name") or {}
    surname = str(name.get("holder_surname") or "").strip()
    first = str(name.get("holder_first_names") or "").strip()
    return " ".join(part for part in (surname, first) if part)


def _driver_ref(card: dict) -> str | None:
    return _holder_name(card) or _card_number(card) or None


def _changes(raw: list) -> list[tuple[int, str, bool, bool]]:
    """Activity changes as (minute, kind, card_out, crew), in time order."""
    out = []
    for change in raw or []:
        if not isinstance(change, dict):
            continue
        kind = _WORK_TYPE.get(change.get("work_type"))
        if kind is None:
            continue
        minute = change.get("minutes")
        if not isinstance(minute, int) or not 0 <= minute <= 1440:
            continue
        # `driver` false means the card sat in the second slot, which is the
        # holder crewing as co-driver. This mirrors what the Go reader marked:
        # the `team` bit is the regulation's own multi-manning flag and would
        # catch more two-up work, but it also relaxes the daily rest rule from
        # 11 hours to 9, so widening it here would quietly report fewer
        # infringements. Left alone deliberately.
        crew = change.get("driver") is False
        out.append((minute, kind, change.get("card_present") is False, crew))
    out.sort(key=lambda item: item[0])
    return out


def _spans(days: list[tuple[datetime, list]]) -> tuple[list[Activity], list[CardGap]]:
    """Daily change records to contiguous spans, plus the card-out periods.

    `days` is [(midnight, changes)], oldest first. Each change opens an
    activity that runs until the next one; the last change of the newest day
    has no recorded end, because the download happened part way through it, so
    it is dropped rather than run to midnight and credited with hours that
    never happened.
    """
    activities: list[Activity] = []
    out_spans: list[tuple[datetime, datetime]] = []

    for index, (day, changes) in enumerate(days):
        newest = index == len(days) - 1
        for position, (minute, kind, card_out, crew) in enumerate(changes):
            if position + 1 < len(changes):
                end_minute = changes[position + 1][0]
            elif newest:
                break
            else:
                end_minute = 1440
            if end_minute <= minute:
                continue
            start = day + timedelta(minutes=minute)
            end = day + timedelta(minutes=end_minute)
            activities.append(Activity(kind, start, end, crew=crew))
            if card_out:
                out_spans.append((start, end))

    gaps: list[CardGap] = []
    for start, end in out_spans:
        if gaps and gaps[-1].end == start:
            gaps[-1] = CardGap(gaps[-1].start, end)
        else:
            gaps.append(CardGap(start, end))
    return activities, gaps


def _midnight(when: datetime) -> datetime:
    return when.replace(hour=0, minute=0, second=0, microsecond=0)


def _places(records: list) -> list[PlaceEntry]:
    out: list[PlaceEntry] = []
    for record in records or []:
        place = (record or {}).get("place_record") or record or {}
        when = _time(place.get("entry_time"))
        if when is None:
            continue
        # entry_type_daily_work_period: even values begin a period, odd end it
        # (0/1 begin and end, 2/3 the same with the card withdrawn).
        entry_type = place.get("entry_type_daily_work_period")
        kind = "end" if isinstance(entry_type, int) and entry_type % 2 else "begin"
        nation = place.get("daily_work_period_country")
        out.append(PlaceEntry(
            when, kind,
            country=0 if not isinstance(nation, int) or nation in _NO_NATION else nation))
    out.sort(key=lambda p: p.time)
    return out


def _odometer(value) -> int | None:
    if not isinstance(value, int) or value in (0, _ODOMETER_UNSET):
        return None
    return value


def _registration(block) -> str:
    """A registration out of a VehicleRegistrationIdentification."""
    if isinstance(block, str):
        return block.strip()
    if not isinstance(block, dict):
        return ""
    return str(block.get("vehicle_registration_number") or "").strip()


def _vehicles(records: list) -> list:
    from app.services.ddd_parser import VehiclePeriod

    out = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        first = _time(record.get("vehicle_first_use"))
        if first is None:
            continue
        plate = record.get("vehicle_registration") or {}
        nation = plate.get("vehicle_registration_nation") if isinstance(plate, dict) else None
        out.append(VehiclePeriod(
            registration=_registration(plate),
            nation=nation if isinstance(nation, int) and nation not in _NO_NATION else 0,
            first_use=first,
            last_use=_time(record.get("vehicle_last_use")),
            odometer_start=_odometer(record.get("vehicle_odometer_begin")),
            odometer_end=_odometer(record.get("vehicle_odometer_end"))))
    out.sort(key=lambda v: v.first_use)
    return out


def _incidents(document: dict, suffix: str) -> list:
    """Events and faults, named from the regulation's own code list."""
    from app.services.ddd_parser import (_EVENT_NAMES, _FAULT_NAMES, CardIncident)

    out = []
    for kind, block_name, array_name, record_name, type_key, names in (
        ("event", f"card_event_data{suffix}", "card_event_records_array",
         "card_event_records", "event_type", _EVENT_NAMES),
        ("fault", f"card_fault_data{suffix}", "card_fault_records_array",
         "card_fault_records", "fault_type", _FAULT_NAMES),
    ):
        block = document.get(block_name) or {}
        # The array is one group per type, each holding that type's records.
        for group in (block.get(array_name) or []):
            for record in (group or {}).get(record_name) or []:
                if not isinstance(record, dict):
                    continue
                start = _time(record.get(f"{kind}_begin_time"))
                if start is None:
                    # Unused slots in the card's fixed-size ring are all zero.
                    continue
                code = record.get(type_key)
                code = code if isinstance(code, int) else 0
                out.append(CardIncident(
                    kind=kind, code=code,
                    name=names.get(code, f"{kind.capitalize()} type 0x{code:02X}"),
                    start=start,
                    end=_time(record.get(f"{kind}_end_time")),
                    registration=_registration(
                        record.get(f"{kind}_vehicle_registration"))))
    out.sort(key=lambda e: e.start)
    return out


def _vu_generation(document: dict) -> tuple[str, str]:
    """Which generation's blocks this VU actually carries.

    A second-generation version 2 unit writes all three sets, so the newest set
    that has activity data is the one to read; a file with no activity at all
    falls back to whichever overview exists so the vehicle is still identified.
    """
    for suffix, label in _GENERATIONS:
        if document.get(f"vu_activities{suffix}"):
            return suffix, label
    for suffix, label in _GENERATIONS:
        if document.get(f"vu_overview{suffix}"):
            return suffix, label
    raise ValueError("vehicle-unit file has no recognised generation data")


def _vu_identity(document: dict, suffix: str) -> tuple[str | None, str | None]:
    """(registration, VIN) from the overview block of either generation."""
    overview = document.get(f"vu_overview{suffix}") or {}

    plate = _one(overview, "vehicle_registration_number_record_array",
                 "vehicle_registration_identification_record_array")
    if plate is None:
        plate = overview.get("vehicle_registration_identification")
    registration = _registration(plate)

    vin = _one(overview, "vehicle_identification_number_record_array")
    if vin is None:
        vin = overview.get("vehicle_identification_number")
    vin = str(vin).strip() if isinstance(vin, (str, int)) else ""

    return registration or None, vin or None


def _vu_serial(document: dict, suffix: str) -> str | None:
    """The tachograph's own serial number, for matching a unit to a vehicle."""
    blocks = document.get(f"vu_technical_data{suffix}") or []
    for block in blocks if isinstance(blocks, list) else [blocks]:
        identification = _one(block, "vu_identification_record_array")
        if identification is None:
            identification = (block or {}).get("vu_identification")
        serial = (identification or {}).get("vu_serial_number")
        if isinstance(serial, dict):
            number = serial.get("serial_number")
            if number is not None:
                return str(number)
        elif serial is not None:
            return str(serial)
    return None


def _vu_cards(blocks: list, suffix: str) -> list[tuple[str, datetime, datetime | None]]:
    """Who held the vehicle's slots, and between when."""
    cards = []
    for block in blocks:
        records = _records(block, "vu_card_iw_record_array")
        if not records:
            records = _records(block.get("vu_card_iw_data") or {}, "vu_card_iw_records")
        for card in records:
            ref = _driver_ref(card)
            inserted = _time((card or {}).get("card_insertion_time"))
            if ref and inserted:
                cards.append((ref, inserted,
                              _time(card.get("card_withdrawal_time"))))
    return cards


def parse_vehicle_unit(data: bytes) -> dict:
    """Parse a vehicle-unit download. Raises ValueError on unusable data."""
    document = _run(data, "vu")
    suffix, generation = _vu_generation(document)

    blocks = document.get(f"vu_activities{suffix}") or []
    if not isinstance(blocks, list):
        blocks = [blocks]

    days: list[tuple[datetime, list]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        # Second generation stamps the day it downloaded; first generation
        # carries the moment the block was written instead.
        day = _time(_one(block, "date_of_day_downloaded_record_array"))
        if day is None:
            day = _time(block.get("time_real"))
        if day is None:
            continue
        changes = _changes(
            _records(block, "vu_activity_daily_record_array")
            or _records(block.get("vu_activity_daily_data") or {}, "activity_change_info"))
        if changes:
            days.append((_midnight(day), changes))
    days.sort(key=lambda item: item[0])

    activities, _gaps = _spans(days)

    # Attach a driver to each span from whichever card was in a slot at the
    # time. Spans with no matching insertion stay vehicle-only.
    cards = _vu_cards([b for b in blocks if isinstance(b, dict)], suffix)
    refs: list[str | None] = [
        next((who for who, inserted, withdrawn in cards
              if activity.end > inserted
              and (withdrawn is None or activity.start < withdrawn)), None)
        for activity in activities
    ]

    registration, vin = _vu_identity(document, suffix)
    # A file with no plate, no VIN and no activity is not a vehicle unit the
    # parser understood - it is something else that happened not to be refused
    # outright, most likely a driver card. Recording that as a good read would
    # file an empty download as a complete one.
    if not registration and not vin and not activities:
        raise ValueError(
            "not a vehicle unit: no registration, VIN or activity data")

    return {
        "activities": activities,
        "activity_driver_refs": refs,
        "days": len({activity.start.date() for activity in activities}),
        "vehicle_ref": registration,
        "vehicle_vin": vin,
        "tachograph_serial": _vu_serial(document, suffix),
        "drivers": sorted({ref for ref in refs if ref}),
        "generation": generation,
        "parser": PARSER_NAME,
        "file_type": "vehicle_unit",
    }


def _card_suffix(document: dict) -> str:
    """Whether to read this card's second- or first-generation blocks.

    A second-generation card holds both, but a card issued before the smart
    tachograph has an empty gen-2 side, and a gen-2 card read by a gen-1 unit
    can have the reverse. Choose by where the activity actually is.
    """
    for suffix in ("_2", "_1"):
        block = document.get(f"card_driver_activity{suffix}") or {}
        if block.get("decoded_activity_daily_records"):
            return suffix
    for suffix in ("_2", "_1"):
        if document.get(
                f"card_identification_and_driver_card_holder_identification{suffix}"):
            return suffix
    return "_1"


def parse_driver_card(data: bytes) -> dict:
    """Parse a driver card. Raises ValueError on unusable data."""
    document = _run(data, "card")
    suffix = _card_suffix(document)

    identification = document.get(
        f"card_identification_and_driver_card_holder_identification{suffix}") or {}
    if not identification:
        raise ValueError("not a driver card: no card holder identification")

    card = identification.get("card_identification") or {}
    holder = identification.get("driver_card_holder_identification") or {}

    activity = document.get(f"card_driver_activity{suffix}") or {}
    days: list[tuple[datetime, list]] = []
    for record in activity.get("decoded_activity_daily_records") or []:
        if not isinstance(record, dict):
            continue
        day = _time(record.get("activity_record_date"))
        if day is None:
            continue
        changes = _changes(record.get("activity_change_info"))
        if changes:
            days.append((_midnight(day), changes))
    days.sort(key=lambda item: item[0])

    activities, gaps = _spans(days)
    if not activities:
        raise ValueError("driver activity block present but no readable records")

    name = _holder_name(holder)
    card_number = str(card.get("card_number") or "").strip()
    expiry = _time(card.get("card_expiry_date"))

    places = document.get(f"card_place_daily_work_period{suffix}") or {}
    vehicles = document.get(f"card_vehicles_used{suffix}") or {}

    return {
        "card_expiry": expiry.date() if expiry else None,
        "activities": activities,
        "places": _places(places.get("place_records") or []),
        "card_gaps": gaps,
        "vehicles": _vehicles(vehicles.get("card_vehicle_records") or []),
        "incidents": _incidents(document, suffix),
        "days": len({activity.start.date() for activity in activities}),
        "card_number": card_number or None,
        "driver_name": name or None,
        "driver_ref": name or card_number or None,
        "parser": PARSER_NAME,
    }

"""Driver-card parsing via the `tachograph` CLI from way-platform/tachograph-go.

That project is an MIT-licensed Go implementation of Regulation (EU) 2016/799,
kept current with the specification, and it covers ground our own reader does
not: second-generation and smart tachograph layouts, the cyclic buffers, and
cryptographic verification of the signatures on each block.

It runs as a separate process and returns JSON, which this module maps onto the
same dictionary the built-in parser returns, so the rules engine and the report
never learn which reader produced their input. If the binary is not configured
or fails, the caller falls back to the built-in reader.

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


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
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

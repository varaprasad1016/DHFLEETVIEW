"""Best-effort driver-card .ddd parser -> normalised activity spans.

Scope: the Gen1 EF_Driver_Activity_Data block (FID 0x0504), which holds the
daily activity change records. This is the part the infringement engine needs.

IMPORTANT: this is a screening parser. The .ddd/TLV layout is well specified but
has generation variants (Gen1/Gen2/Gen2v2) and a cyclic buffer; validate the
output against your real card files before relying on the infringements. On any
doubt the caller archives the file and marks it unparsed rather than inventing
activity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.services.tacho_rules import Activity, CardGap, PlaceEntry

EVENTS_FID = 0x0502
FAULTS_FID = 0x0503
DRIVER_ACTIVITY_FID = 0x0504
VEHICLES_FID = 0x0505
PLACES_FID = 0x0506
IDENTIFICATION_FID = 0x0520
_ACTIVITY = {0: "rest", 1: "available", 2: "work", 3: "drive"}
_PLACE_RECORD = 10          # entryTime(4) type(1) country(1) region(1) odo(3)
_VEHICLE_RECORD = 31        # odo begin(3) end(3) first(4) last(4) reg(15) counter(2)
_EVENT_RECORD = 24          # type(1) begin(4) end(4) reg(15)
_ODO_UNSET = 0xFFFFFF
_TIME_UNSET = 0xFFFFFFFF

# The event and fault codes an operator is most likely to be asked about. Any
# code not listed is reported by its number rather than guessed at.
_EVENT_NAMES = {
    0x01: "Insertion of a non-valid card",
    0x02: "Card conflict",
    0x03: "Time overlap",
    0x04: "Driving without an appropriate card",
    0x05: "Card insertion while driving",
    0x06: "Last card session not correctly closed",
    0x07: "Over speeding",
    0x08: "Power supply interruption",
    0x09: "Motion data error",
    0x0A: "Vehicle motion conflict",
    0x11: "No further details",
    0x12: "Motion sensor authentication failure",
    0x13: "Tachograph authentication failure",
    0x14: "Unauthorised change of motion sensor",
    0x15: "Card data input integrity error",
    0x16: "Stored user data integrity error",
    0x17: "Internal data transfer error",
    0x18: "Unauthorised case opening",
    0x19: "Hardware sabotage",
}
_FAULT_NAMES = {
    0x31: "Tachograph fault",
    0x32: "Sensor fault",
    0x51: "Card fault",
    0x52: "Recording equipment fault",
}


@dataclass
class VehiclePeriod:
    """One spell in one vehicle, as the card records it."""
    registration: str
    nation: int
    first_use: datetime | None
    last_use: datetime | None
    odometer_start: int | None
    odometer_end: int | None

    @property
    def distance(self) -> int | None:
        if self.odometer_start is None or self.odometer_end is None:
            return None
        return max(0, self.odometer_end - self.odometer_start)


@dataclass
class CardIncident:
    """An event or a fault the tachograph recorded against this card."""
    kind: str              # event | fault
    code: int
    name: str
    start: datetime
    end: datetime | None
    registration: str = ""


def _iter_blocks(data: bytes):
    """Yield (fid, type_byte, value) TLV blocks: FID(2) type(1) len(2) value."""
    i, n = 0, len(data)
    while i + 5 <= n:
        fid = int.from_bytes(data[i:i + 2], "big")
        type_byte = data[i + 2]
        length = int.from_bytes(data[i + 3:i + 5], "big")
        start = i + 5
        end = start + length
        if end > n or length == 0:
            break
        yield fid, type_byte, data[start:end]
        i = end


def _parse_activity_block(value: bytes) -> tuple[list[Activity], list[CardGap]]:
    """value = activityPointerOldest(2) + activityPointerNewest(2) + cyclic buffer.

    Returns the activity spans and the periods the card spent out of a
    tachograph, which the records flag alongside each activity.
    """
    if len(value) < 4:
        return [], []
    buf = value[4:]
    # per day: (midnight, [(minute, activity, card was out), ...])
    records: list[tuple[datetime, list[tuple[int, str, bool]]]] = []
    off, guard = 0, 0
    while off + 12 <= len(buf) and guard < 4000:
        guard += 1
        rec_len = int.from_bytes(buf[off + 2:off + 4], "big")
        if rec_len < 12 or off + rec_len > len(buf):
            break
        date_secs = int.from_bytes(buf[off + 4:off + 8], "big")
        day0 = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=date_secs)
        # normalise to midnight of the record day
        day0 = day0.replace(hour=0, minute=0, second=0, microsecond=0)

        aci = buf[off + 12:off + rec_len]
        changes = []
        for j in range(0, len(aci) - 1, 2):
            word = int.from_bytes(aci[j:j + 2], "big")
            slot = (word >> 15) & 1
            if slot != 0:            # driver slot only
                continue
            activity = (word >> 11) & 0x03
            card_out = (word >> 13) & 1  # 1 = the card was not in a tachograph
            minute = word & 0x7FF
            if minute <= 1440:
                changes.append((minute, _ACTIVITY[activity], bool(card_out)))
        changes.sort(key=lambda c: c[0])
        records.append((day0, changes))
        off += rec_len

    acts: list[Activity] = []
    out_spans: list[tuple[datetime, datetime]] = []
    for r, (day0, changes) in enumerate(records):
        last_record = r == len(records) - 1
        for k, (minute, typ, card_out) in enumerate(changes):
            if k + 1 < len(changes):
                end_min = changes[k + 1][0]
            elif last_record:
                # The newest record is still open: the card was downloaded part
                # way through the day and the final activity has no recorded
                # end. Running it to midnight would invent up to a day of work
                # and raise infringements the driver never committed, so the
                # timeline simply stops at the last change.
                break
            else:
                end_min = 1440
            if end_min > minute:
                start = day0 + timedelta(minutes=minute)
                end = day0 + timedelta(minutes=end_min)
                acts.append(Activity(typ, start, end))
                if card_out:
                    out_spans.append((start, end))

    # One withdrawal shows up as a run of spans, one per activity and one per
    # calendar day it crosses; join them back into the period the card was out.
    gaps: list[CardGap] = []
    for start, end in out_spans:
        if gaps and gaps[-1].end == start:
            gaps[-1] = CardGap(gaps[-1].start, end)
        else:
            gaps.append(CardGap(start, end))
    return acts, gaps


def _parse_places(value: bytes) -> list[PlaceEntry]:
    """EF_Places: a pointer byte then fixed-size records of the places entered
    at the start and end of each daily work period. Even entry types are a
    start, odd ones an end; an empty slot has a zero timestamp."""
    out: list[PlaceEntry] = []
    body = value[1:]
    for i in range(len(body) // _PLACE_RECORD):
        rec = body[i * _PLACE_RECORD:(i + 1) * _PLACE_RECORD]
        stamp = int.from_bytes(rec[0:4], "big")
        if not stamp:
            continue
        entry_type = rec[4]
        out.append(PlaceEntry(
            datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=stamp),
            "end" if entry_type % 2 else "begin",
            rec[5]))
    out.sort(key=lambda p: p.time)
    return out


def _string(raw: bytes) -> str:
    """A card string: one code-page byte then padded characters."""
    return raw[1:].decode("latin-1", "replace").strip().strip("\x00").strip()


def _time(raw: bytes) -> datetime | None:
    """A TimeReal. Zero means never set; all-ones means still open."""
    value = int.from_bytes(raw, "big")
    if not value or value >= _TIME_UNSET:
        return None
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=value)


def _parse_vehicles(value: bytes) -> list[VehiclePeriod]:
    """EF_Vehicles_Used: a pointer then one record per spell in a vehicle,
    holding the registration and the odometer at each end of the spell."""
    out: list[VehiclePeriod] = []
    body = value[2:]
    for i in range(len(body) // _VEHICLE_RECORD):
        rec = body[i * _VEHICLE_RECORD:(i + 1) * _VEHICLE_RECORD]
        first = _time(rec[6:10])
        if first is None:
            continue                       # empty slot
        odo_start = int.from_bytes(rec[0:3], "big")
        odo_end = int.from_bytes(rec[3:6], "big")
        out.append(VehiclePeriod(
            registration=_string(rec[15:29]),
            nation=rec[14],
            first_use=first,
            last_use=_time(rec[10:14]),
            odometer_start=None if odo_start == _ODO_UNSET else odo_start,
            # The newest spell is still running, so its closing odometer and
            # last-use time are not written yet.
            odometer_end=None if odo_end == _ODO_UNSET else odo_end))
    out.sort(key=lambda v: v.first_use)
    return out


def _parse_incidents(value: bytes, kind: str) -> list[CardIncident]:
    """EF_Events_Data / EF_Faults_Data: fixed-size records, empty slots zeroed."""
    names = _EVENT_NAMES if kind == "event" else _FAULT_NAMES
    out: list[CardIncident] = []
    for i in range(len(value) // _EVENT_RECORD):
        rec = value[i * _EVENT_RECORD:(i + 1) * _EVENT_RECORD]
        start = _time(rec[1:5])
        if start is None:
            continue
        code = rec[0]
        out.append(CardIncident(
            kind=kind, code=code,
            name=names.get(code, f"{kind.title()} code 0x{code:02X}"),
            start=start, end=_time(rec[5:9]),
            registration=_string(rec[10:24])))
    out.sort(key=lambda e: e.start)
    return out


def _parse_identification(value: bytes) -> dict:
    """EF_Identification: CardIdentification (65 bytes) then the card holder's
    surname and first names (36 bytes each)."""
    if len(value) < 137:
        return {}
    return {
        "card_number": value[1:17].decode("latin-1", "replace").strip().strip("\x00"),
        "surname": _string(value[65:101]),
        "first_names": _string(value[101:137]),
    }


def parse_vehicle_unit_company(data: bytes) -> str | None:
    """Read the fixed company/operator field from a Gen1 VU overview.

    The overview stores this field at bytes 456..490 (inclusive). Keep this
    best-effort: an upload must still be archived if a generation/vendor uses
    a different layout.
    """
    raw = data[456:491] if len(data) >= 491 else b""
    value = raw.decode("latin-1", "replace").replace("\x00", " ").strip()
    return value if value and any(character.isalnum() for character in value) else None


def parse_driver_card(data: bytes) -> dict:
    """Return {'activities': [...], 'days': n} plus whatever the card says about
    its holder. Raises ValueError if no driver activity block is found (the
    caller then archives the file as unparsed)."""
    acts: list[Activity] | None = None
    gaps: list[CardGap] = []
    places: list[PlaceEntry] = []
    vehicles: list[VehiclePeriod] = []
    incidents: list[CardIncident] = []
    ident: dict = {}
    for fid, type_byte, value in _iter_blocks(data):
        if type_byte != 0x00:
            continue                       # 0x01 blocks are the signatures
        if fid == DRIVER_ACTIVITY_FID and acts is None:
            acts, gaps = _parse_activity_block(value)
        elif fid == PLACES_FID and not places:
            places = _parse_places(value)
        elif fid == VEHICLES_FID and not vehicles:
            vehicles = _parse_vehicles(value)
        elif fid == EVENTS_FID:
            incidents += _parse_incidents(value, "event")
        elif fid == FAULTS_FID:
            incidents += _parse_incidents(value, "fault")
        elif fid == IDENTIFICATION_FID and not ident:
            ident = _parse_identification(value)
    incidents.sort(key=lambda e: e.start)
    if acts is None:
        raise ValueError("no driver activity block (FID 0x0504) found")
    if not acts:
        raise ValueError("driver activity block present but no readable records")

    name = " ".join(p for p in (ident.get("surname"), ident.get("first_names")) if p)
    return {
        "activities": acts,
        "places": places,
        "card_gaps": gaps,
        "vehicles": vehicles,
        "incidents": incidents,
        "days": len({a.start.date() for a in acts}),
        "card_number": ident.get("card_number") or None,
        "driver_name": name or None,
        # What to file the infringements under, best identifier first.
        "driver_ref": (name or ident.get("card_number") or None),
    }

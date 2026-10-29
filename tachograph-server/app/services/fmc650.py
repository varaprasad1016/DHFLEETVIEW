"""Tachograph live data sent by Teltonika FMC650 trackers (CAN2 to the tachograph).

DH FleetView (Traccar) decodes the FMC650's AVL records and stores unmapped IO
elements as position attributes named ``io<AVL ID>``. This module turns those
attributes into per-driver-slot readings. AVL IDs and encodings are from
Teltonika's "FMC650 Teltonika Data Sending Parameters ID" (Tachograph data
elements) and "How to read Driver ID".

Values are sent on change, so a record usually carries only some of them:
callers merge readings into the last known state.
"""

from __future__ import annotations

from datetime import datetime, timezone

WORKING_STATES = {0: "rest", 1: "available", 2: "work", 3: "drive"}   # 6 error, 7 not available

# Driver 1 / 2 "Time Related States" (AVL 189 / 190): (label, level)
TIME_STATES = {
    1: ("15 min before 4h30 driving", "warn"),
    2: ("4h30 driving reached — take a break", "bad"),
    3: ("15 min before 9h daily driving", "warn"),
    4: ("9h daily driving reached", "bad"),
    5: ("15 min before 16h", "warn"),
    6: ("16h reached", "bad"),
    7: ("Weekly driving time pre-warning", "warn"),
    8: ("Weekly driving time limit reached", "bad"),
    9: ("Two-week driving time pre-warning", "warn"),
    10: ("Two-week driving time limit reached", "bad"),
    11: ("Driver card expiry warning", "warn"),
    12: ("Driver card download due", "warn"),
}

# field -> (driver 1 AVL ID, driver 2 AVL ID); None where Teltonika has no driver 2 element.
MINUTES = {
    "continuous_driving": (56, 57),
    "cumulative_break": (58, 59),
    "activity_duration": (60, 61),
    "two_week_driving": (69, 77),
    "daily_driving": (10507, 10514),
    "weekly_driving": (10508, 10515),
    "until_daily_rest": (10509, 10516),
    "until_weekly_rest": (10522, 10523),
    "min_daily_rest": (10524, 10525),
    "min_weekly_rest": (10526, 10527),
    "next_break_duration": (10528, 10529),
    "until_break": (10530, 10531),
    "remaining_current_driving": (10532, None),
    "remaining_shift_driving": (10533, None),
    "remaining_week_driving": (10534, None),
    "remaining_current_break": (10539, None),
    "until_next_driving": (10540, None),
    "next_driving_duration": (10541, None),
}
COUNTS = {"daily_extensions_used": (10510, 10517)}
TIMESTAMPS = {
    "end_last_daily_rest": (10504, 10511),
    "end_last_weekly_rest": (10505, 10512),
}
SLOT_IDS = {
    "working_state": (184, 185),
    "card_present": (187, 188),
    "time_state": (189, 190),
    "id_msb": (195, 197),
    "id_lsb": (196, 198),
    "first_name": (10518, 10520),
    "surname": (10519, 10521),
}
VEHICLE_IDS = {"no_card_driving": 52, "tacho_source": 48, "overspeed": 186}

ALL_IDS = {i for pair in (*MINUTES.values(), *COUNTS.values(), *TIMESTAMPS.values(), *SLOT_IDS.values())
           for i in pair if i is not None} | set(VEHICLE_IDS.values())


def _attr(attrs: dict, avl_id: int | None):
    return None if avl_id is None else attrs.get(f"io{avl_id}")


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def has_tacho_data(attrs: dict) -> bool:
    return any(f"io{i}" in attrs for i in ALL_IDS)


def _mirrored_ascii(value) -> str:
    """One half of a driver ID: 8 bytes of ASCII, sent mirrored."""
    number = _int(value)
    if number is None:
        return ""
    raw = (number & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "big")
    return raw.decode("latin-1")[::-1]


def driver_id(msb, lsb) -> str | None:
    """Driver card number from the MSB/LSB elements (e.g. 195/196).

    Teltonika example: 3544385890265608240 / 4123102840462782769 -> "0000000111020489".
    """
    text = (_mirrored_ascii(msb) + _mirrored_ascii(lsb)).replace("\x00", "").strip()
    if not text or not all(32 < ord(c) < 127 for c in text) or set(text) == {"0"}:
        return None
    return text


def card_text(value) -> str | None:
    """Driver name elements: hex, first byte is the ISO/IEC 8859 code page."""
    if not isinstance(value, str) or len(value) < 4:
        return None
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        return None
    text = raw[1:].decode("latin-1").replace("\x00", "").strip()
    return text or None


def _timestamp(value) -> str | None:
    seconds = _int(value)
    if not seconds or seconds >= 0xFFFFFFFF:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def slot_reading(attrs: dict, slot: int) -> dict:
    """Only the values present in this record, decoded, for driver slot 1 or 2."""
    i = slot - 1
    out: dict = {}
    if (v := _int(_attr(attrs, SLOT_IDS["working_state"][i]))) is not None:
        out["working_state"] = WORKING_STATES.get(v)          # None = error / not available
    if (v := _int(_attr(attrs, SLOT_IDS["card_present"][i]))) is not None:
        out["card_present"] = {0: False, 1: True}.get(v)      # None = error / privacy mode
    if (v := _int(_attr(attrs, SLOT_IDS["time_state"][i]))) is not None:
        out["time_state"] = v
    msb, lsb = _attr(attrs, SLOT_IDS["id_msb"][i]), _attr(attrs, SLOT_IDS["id_lsb"][i])
    if msb is not None or lsb is not None:
        out["card_number"] = driver_id(msb, lsb)
    first, last = card_text(_attr(attrs, SLOT_IDS["first_name"][i])), card_text(_attr(attrs, SLOT_IDS["surname"][i]))
    if first or last:
        out["card_holder"] = " ".join(x for x in (last, first) if x)
    for name, ids in MINUTES.items():
        v = _int(_attr(attrs, ids[i]))
        if v is not None:
            out[name] = None if v >= 0xFFFF else v             # 0xFFFF = not available
    for name, ids in COUNTS.items():
        v = _int(_attr(attrs, ids[i]))
        if v is not None:
            out[name] = None if v >= 0xFF else v
    for name, ids in TIMESTAMPS.items():
        v = _attr(attrs, ids[i])
        if v is not None:
            out[name] = _timestamp(v)
    if slot == 1 and (v := _int(_attr(attrs, VEHICLE_IDS["no_card_driving"]))) is not None:
        out["no_card_driving"] = v == 1
    return out


def figures(values: dict) -> dict:
    """Driver-facing limits: the tachograph's own figures, with fallbacks worked
    out from what it reported when a model doesn't send the "remaining" values."""
    def pick(key, fallback):
        return values[key] if values.get(key) is not None else fallback

    cont = values.get("continuous_driving")
    daily = values.get("daily_driving")
    weekly = values.get("weekly_driving")
    fortnight = values.get("two_week_driving")
    ext_used = values.get("daily_extensions_used")
    daily_limit = 600 if ext_used is not None and ext_used < 2 else 540
    return {
        "driving_until_break": pick("until_break", pick("remaining_current_driving",
                                                        None if cont is None else max(0, 270 - cont))),
        "driving_left_today": pick("remaining_shift_driving", None if daily is None else max(0, daily_limit - daily)),
        "driving_left_week": pick("remaining_week_driving", None if weekly is None else max(0, 3360 - weekly)),
        "driving_left_fortnight": None if fortnight is None else max(0, 5400 - fortnight),
        "continuous_driving": cont,
        "break_taken": values.get("cumulative_break"),
        "daily_driving": daily,
        "weekly_driving": weekly,
        "two_week_driving": fortnight,
        "next_break_duration": values.get("next_break_duration"),
        "until_daily_rest": values.get("until_daily_rest"),
        "until_weekly_rest": values.get("until_weekly_rest"),
        "min_daily_rest": values.get("min_daily_rest"),
        "min_weekly_rest": values.get("min_weekly_rest"),
        "remaining_current_break": values.get("remaining_current_break"),
        "daily_extensions_used": ext_used,
        "end_last_daily_rest": values.get("end_last_daily_rest"),
        "end_last_weekly_rest": values.get("end_last_weekly_rest"),
    }


def warning(time_state: int | None) -> dict | None:
    if time_state in TIME_STATES:
        label, level = TIME_STATES[time_state]
        return {"code": time_state, "label": label, "level": level}
    return None

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

from datetime import datetime, timedelta, timezone

from app.services.tacho_rules import Activity

DRIVER_ACTIVITY_FID = 0x0504
_ACTIVITY = {0: "rest", 1: "available", 2: "work", 3: "drive"}


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


def _parse_activity_block(value: bytes) -> list[Activity]:
    """value = activityPointerOldest(2) + activityPointerNewest(2) + cyclic buffer."""
    if len(value) < 4:
        return []
    buf = value[4:]
    acts: list[Activity] = []
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
            minute = word & 0x7FF
            if minute <= 1440:
                changes.append((minute, _ACTIVITY[activity]))
        changes.sort(key=lambda c: c[0])
        # a change marks the START of an activity that runs to the next change (or day end)
        for k, (minute, typ) in enumerate(changes):
            end_min = changes[k + 1][0] if k + 1 < len(changes) else 1440
            if end_min > minute:
                acts.append(Activity(typ, day0 + timedelta(minutes=minute),
                                     day0 + timedelta(minutes=end_min)))
        off += rec_len
    return acts


def parse_driver_card(data: bytes) -> dict:
    """Return {'activities': [...], 'days': n}. Raises ValueError if no driver
    activity block is found (caller then archives it as unparsed)."""
    for fid, type_byte, value in _iter_blocks(data):
        if fid == DRIVER_ACTIVITY_FID and type_byte == 0x00:
            acts = _parse_activity_block(value)
            if not acts:
                raise ValueError("driver activity block present but no readable records")
            days = len({a.start.date() for a in acts})
            return {"activities": acts, "days": days}
    raise ValueError("no driver activity block (FID 0x0504) found")

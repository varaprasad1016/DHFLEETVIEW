"""Live tachograph data from FMC650 trackers: ingest, current state, provisional
activity and mismatch checks.

How the sources rank: a signed driver-card download is the legal record and
always wins for the period it covers. Live data only fills the time since the
driver's last download, and is compared with the download once it arrives.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tacho import TachoActivity, TachoFile
from app.models.tacho_live import TachoLiveActivity, TachoLiveAlert, TachoLiveStatus
from app.services import fmc650
from app.services.tacho_scope import card_key, primary_reg

LONDON = ZoneInfo("Europe/London")
FRESH = timedelta(hours=24)          # statuses older than this are not "live"
STALE = timedelta(minutes=10)        # no record for this long: show as possibly out of date
RESTING = ("rest", "available")
VALUE_FIELDS = set(fmc650.MINUTES) | set(fmc650.COUNTS) | set(fmc650.TIMESTAMPS)
LIMIT_CODES = (2, 4, 6, 8, 10)       # "reached" time-related states


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --- ingest ----------------------------------------------------------------------------------

async def ingest(session: AsyncSession, payload: dict, now: datetime | None = None) -> dict:
    """One DH FleetView forwarded position ({"position": ..., "device": ...})."""
    position = payload.get("position") or {}
    device = payload.get("device") or {}
    attrs = position.get("attributes") or {}
    if not fmc650.has_tacho_data(attrs):
        return {"tacho": False}
    uid = str(device.get("uniqueId") or position.get("deviceId") or "").strip()
    ts = _parse_time(position.get("deviceTime")) or _parse_time(position.get("fixTime")) or now or datetime.now(timezone.utc)
    if not uid:
        return {"tacho": False, "error": "no device"}
    vehicle = {"traccar_device_id": device.get("id") or position.get("deviceId"),
               "vehicle_name": (device.get("name") or "")[:120] or None,
               "vehicle_reg": primary_reg(device)[:20] or None}
    applied = []
    for slot in (1, 2):
        reading = fmc650.slot_reading(attrs, slot)
        if not any(k in reading for k in ("working_state", "card_present", "card_number", "time_state")) \
                and not (set(reading) & VALUE_FIELDS - {"continuous_driving"}):
            continue
        for attempt in (1, 2):
            try:
                applied.append(await _apply_slot(session, uid, vehicle, ts, slot, reading))
                await session.commit()
                break
            except IntegrityError:           # two records for a new slot at once
                await session.rollback()
                if attempt == 2:
                    raise
    return {"tacho": True, "slots": applied}


async def _apply_slot(session: AsyncSession, uid: str, vehicle: dict, ts: datetime, slot: int, reading: dict) -> dict:
    status = (await session.execute(
        select(TachoLiveStatus).where(TachoLiveStatus.device_uid == uid, TachoLiveStatus.slot == slot).with_for_update()
    )).scalar_one_or_none()
    if status is not None and ts < status.recorded_at:
        return {"slot": slot, "ignored": "older than the current state"}
    if status is None:
        status = TachoLiveStatus(device_uid=uid, slot=slot, recorded_at=ts, values={})
        session.add(status)
        await session.flush()
    for key, value in vehicle.items():
        if value is not None:
            setattr(status, key, value)

    values = dict(status.values or {})
    for key in set(reading) & VALUE_FIELDS:
        values[key] = reading[key]
    status.values = values
    if "card_present" in reading:
        status.card_present = reading["card_present"]
    if "card_number" in reading:
        status.card_number = reading["card_number"]
    if status.card_present is False:
        status.card_number = None
        status.card_holder = None
    if "card_holder" in reading:
        status.card_holder = reading["card_holder"]
    if "time_state" in reading:
        status.time_state = reading["time_state"]
    state = reading["working_state"] if "working_state" in reading else status.working_state
    card = status.card_number

    if slot == 1 and "no_card_driving" in reading:      # AVL 52 is only sent when it changes: remember it
        values["no_card_signal"] = reading["no_card_driving"]
        status.values = values
    driving_without_card = bool(
        (slot == 1 and values.get("no_card_signal") and state in ("drive", None))
        or (state == "drive" and status.card_present is False))
    status.no_card_driving = driving_without_card

    # Activity spans: one open span per slot; a new one when the card or activity changes.
    tracked = state if (card or (state == "drive" and driving_without_card)) else None
    open_span = (await session.execute(
        select(TachoLiveActivity).where(TachoLiveActivity.device_uid == uid, TachoLiveActivity.slot == slot,
                                        TachoLiveActivity.ended_at.is_(None))
    )).scalars().first()
    gap_closed = open_span is not None and _span_end(open_span, ts) < ts   # no data for longer than the span can run on
    if open_span and not gap_closed and open_span.card_number == card and open_span.activity_type == tracked:
        open_span.last_seen_at = ts
    else:
        if open_span:
            # Close where the data says it ended: at this record, or where the data stopped.
            open_span.ended_at = max(open_span.started_at, _span_end(open_span, ts))
        if tracked:
            duration = reading.get("activity_duration") if "working_state" in reading else None
            start = ts - timedelta(minutes=duration) if duration is not None and duration < 24 * 60 else ts
            if open_span and start < open_span.ended_at:
                start = open_span.ended_at
            session.add(TachoLiveActivity(device_uid=uid, vehicle_reg=status.vehicle_reg, slot=slot, card_number=card,
                                          activity_type=tracked, started_at=start, ended_at=None, last_seen_at=ts))
            status.state_since = start
        else:
            status.state_since = ts
    status.working_state = state
    status.recorded_at = ts
    status.updated_at = datetime.now(timezone.utc)

    await _alerts(session, status, ts)
    return {"slot": slot, "card": bool(card), "activity": state}


async def _alerts(session: AsyncSession, status: TachoLiveStatus, ts: datetime) -> None:
    open_no_card = (await session.execute(
        select(TachoLiveAlert).where(TachoLiveAlert.kind == "no_card_driving", TachoLiveAlert.device_uid == status.device_uid,
                                     TachoLiveAlert.ended_at.is_(None))
    )).scalars().first()
    if status.no_card_driving and open_no_card is None:
        session.add(TachoLiveAlert(
            kind="no_card_driving", device_uid=status.device_uid, vehicle_reg=status.vehicle_reg, slot=status.slot,
            title=f"{status.vehicle_name or status.vehicle_reg or status.device_uid} is being driven without a driver card",
            started_at=ts, dedup_key=f"no_card|{status.device_uid}|{ts.isoformat()}"))
    elif open_no_card is not None and not status.no_card_driving:
        open_no_card.ended_at = ts

    if status.time_state in fmc650.TIME_STATES and status.time_state in LIMIT_CODES and status.card_number:
        day = ts.astimezone(LONDON).date().isoformat()
        key = f"limit{status.time_state}|{card_key(status.card_number)}|{day}"
        exists = (await session.execute(select(TachoLiveAlert.id).where(TachoLiveAlert.dedup_key == key))).first()
        if not exists:
            who = status.card_holder or f"card …{status.card_number[-4:]}"
            session.add(TachoLiveAlert(
                kind=f"limit_{status.time_state}", device_uid=status.device_uid, vehicle_reg=status.vehicle_reg,
                slot=status.slot, card_number=status.card_number, started_at=ts, ended_at=ts, dedup_key=key,
                title=f"{who}: {fmc650.TIME_STATES[status.time_state][0]}"))


# --- reading -----------------------------------------------------------------------------------

def status_view(status: TachoLiveStatus, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "device_uid": status.device_uid,
        "vehicle_name": status.vehicle_name,
        "vehicle_reg": status.vehicle_reg,
        "slot": status.slot,
        "card_number": status.card_number,
        "card_holder": status.card_holder,
        "card_present": status.card_present,
        "activity": status.working_state,
        "since": status.state_since.isoformat() if status.state_since else None,
        "recorded_at": status.recorded_at.isoformat(),
        "stale": now - status.recorded_at > STALE,
        "no_card_driving": status.no_card_driving,
        "warning": fmc650.warning(status.time_state),
        # Driving-time figures belong to a driver card: none without one.
        "figures": fmc650.figures(status.values or {}) if status.card_number else {},
    }


async def fresh_statuses(session: AsyncSession, now: datetime | None = None) -> list[TachoLiveStatus]:
    now = now or datetime.now(timezone.utc)
    return (await session.execute(
        select(TachoLiveStatus).where(TachoLiveStatus.recorded_at >= now - FRESH).order_by(TachoLiveStatus.recorded_at.desc())
    )).scalars().all()


async def status_for_card(session: AsyncSession, key: str, now: datetime | None = None) -> TachoLiveStatus | None:
    """The freshest live state for a driver card (first 14 characters)."""
    if len(key) < 14:
        return None
    for status in await fresh_statuses(session, now):
        if status.card_number and card_key(status.card_number) == key:
            return status
    return None


def _span_end(span: TachoLiveActivity, now: datetime) -> datetime:
    if span.ended_at is not None:
        return span.ended_at
    # Still open: rest carries on while the tracker sleeps; driving/work stop where data stops.
    grace = timedelta(hours=12) if span.activity_type in RESTING else STALE
    return min(now, span.last_seen_at + grace)


async def live_spans(session: AsyncSession, key: str, since: datetime, until: datetime | None = None,
                     now: datetime | None = None) -> list[tuple[str, datetime, datetime]]:
    """Provisional activity for a driver card between two times, clipped."""
    now = now or datetime.now(timezone.utc)
    until = until or now
    rows = (await session.execute(
        select(TachoLiveActivity).where(
            TachoLiveActivity.card_number.is_not(None), TachoLiveActivity.started_at < until,
            or_(TachoLiveActivity.ended_at.is_(None), TachoLiveActivity.ended_at > since))
        .order_by(TachoLiveActivity.started_at)
    )).scalars().all()
    out = []
    for span in rows:
        if card_key(span.card_number) != key:
            continue
        start, end = max(span.started_at, since), min(_span_end(span, now), until)
        if end > start:
            out.append((span.activity_type, start, end))
    return out


async def download_coverage(session: AsyncSession, key: str) -> datetime | None:
    """Where the driver's downloaded card data ends: live data only counts after this."""
    if len(key) < 14:
        return None
    rows = (await session.execute(
        select(TachoFile.id, TachoFile.card_number).where(TachoFile.file_kind == "driver_card", TachoFile.card_number.is_not(None))
    )).all()
    ids = [fid for fid, number in rows if card_key(number) == key]
    if not ids:
        return None
    return (await session.execute(
        select(func.max(TachoActivity.ended_at)).where(TachoActivity.source_file_id.in_(ids))
    )).scalar_one()


def minutes_by_day(spans) -> dict[str, dict[str, int]]:
    days: dict[str, dict[str, int]] = {}
    for kind, start, end in spans:
        cursor = start
        while cursor < end:
            local = cursor.astimezone(LONDON)
            next_midnight = (local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).astimezone(timezone.utc)
            piece_end = min(end, next_midnight)
            bucket = days.setdefault(local.date().isoformat(), {"drive": 0, "work": 0, "available": 0, "rest": 0})
            if kind in bucket:
                bucket[kind] += int((piece_end - cursor).total_seconds() // 60)
            cursor = piece_end
    return days


async def mismatches(session: AsyncSession, key: str, days: int = 14, threshold: int = 15,
                     now: datetime | None = None) -> list[dict]:
    """Days where live data and the downloaded card disagree (the download is the record)."""
    now = now or datetime.now(timezone.utc)
    coverage = await download_coverage(session, key)
    if coverage is None:
        return []
    since = coverage - timedelta(days=days)   # the last `days` days the download covers
    live = minutes_by_day(await live_spans(session, key, since, coverage, now))
    if not live:
        return []
    rows = (await session.execute(
        select(TachoFile.id, TachoFile.card_number).where(TachoFile.file_kind == "driver_card", TachoFile.card_number.is_not(None))
    )).all()
    ids = [fid for fid, number in rows if card_key(number) == key]
    acts = (await session.execute(
        select(TachoActivity.activity_type, TachoActivity.started_at, TachoActivity.ended_at).where(
            TachoActivity.source_file_id.in_(ids), TachoActivity.ended_at > since, TachoActivity.started_at < coverage)
    )).all()
    card = minutes_by_day([(t.lower(), max(s, since), min(e, coverage)) for t, s, e in acts])
    out = []
    for day, lv in sorted(live.items()):
        cd = card.get(day, {"drive": 0, "work": 0, "available": 0, "rest": 0})
        diff = {k: lv[k] - cd[k] for k in ("drive", "work")}
        if any(abs(v) >= threshold for v in diff.values()):
            out.append({"date": day, "live": lv, "card": cd, "difference": diff})
    return out

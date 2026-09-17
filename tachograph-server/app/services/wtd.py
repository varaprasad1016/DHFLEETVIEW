"""Road Transport (Working Time) Regulations: weekly working time from driver card data.

Working time = driving + other work. Periods of availability (POA), breaks and
rest don't count. Checked here:

- no more than 60 hours' working time in any single week;
- an average of no more than 48 hours a week over the reference period
  (rolling 17 weeks by default; 26 weeks where a workforce agreement allows);
- on days with night work (any working time between 00:00 and 04:00 for goods
  vehicle drivers), no more than 10 hours' working time in the 24 hours from the
  start of that day's work.

The average only counts weeks with working time on the card: weeks of leave or
sickness are left out rather than counted as zero hours. The break rules (6h without a break, 30/45
minute breaks) are checked by the infringement engine and shown alongside.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
WEEK_LIMIT = 60 * 60
AVERAGE_LIMIT = 48 * 60
NIGHT_LIMIT = 10 * 60
NIGHT_START, NIGHT_END = time(0, 0), time(4, 0)
WORKING = ("drive", "work")


def dedupe(spans) -> list[tuple[str, datetime, datetime]]:
    """Card data uploaded more than once repeats the same spans exactly."""
    return sorted({(k.lower(), s, e) for k, s, e in spans if e > s}, key=lambda x: x[1])


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _split_days(kind: str, start: datetime, end: datetime):
    """Yield (local date, minutes, local start, local end) pieces cut at London midnight."""
    cursor = start
    while cursor < end:
        local = cursor.astimezone(LONDON)
        midnight = datetime.combine(local.date() + timedelta(days=1), time(0), LONDON).astimezone(timezone.utc)
        piece_end = min(end, midnight)
        yield local.date(), int((piece_end - cursor).total_seconds() // 60), local, piece_end.astimezone(LONDON)
        cursor = piece_end


def daily(spans) -> dict[date, dict]:
    """Per London day: drive/work/available/rest minutes, first/last working time, night work."""
    days: dict[date, dict] = defaultdict(lambda: {"drive": 0, "work": 0, "available": 0, "rest": 0,
                                                    "first": None, "last": None, "night": False})
    for kind, start, end in dedupe(spans):
        for day, minutes, lstart, lend in _split_days(kind, start, end):
            d = days[day]
            if kind in d:
                d[kind] += minutes
            if kind in WORKING:
                d["first"] = lstart if d["first"] is None or lstart < d["first"] else d["first"]
                d["last"] = lend if d["last"] is None or lend > d["last"] else d["last"]
                night_end = datetime.combine(day, NIGHT_END, LONDON)
                if lstart < night_end:
                    d["night"] = True
    return dict(days)


def _working_in_24h(spans, start: datetime) -> int:
    end = start + timedelta(hours=24)
    total = 0
    for kind, s, e in spans:
        if kind in WORKING and s < end and e > start:
            total += int((min(e, end) - max(s, start)).total_seconds() // 60)
    return total


def report(spans, weeks: int = 26, reference_weeks: int = 17, today: date | None = None) -> dict:
    spans = dedupe(spans)
    today = today or datetime.now(LONDON).date()
    days = daily(spans)
    last_week = week_start(today)
    first_week = last_week - timedelta(weeks=weeks - 1)
    history_start = first_week - timedelta(weeks=reference_weeks - 1)

    weekly: dict[date, dict] = {}
    for day, d in days.items():
        ws = week_start(day)
        if ws < history_start or ws > last_week:
            continue
        w = weekly.setdefault(ws, {"drive": 0, "work": 0, "available": 0, "night_days": 0, "night_over_10h": []})
        w["drive"] += d["drive"]
        w["work"] += d["work"]
        w["available"] += d["available"]
        if d["night"]:
            w["night_days"] += 1
            if d["first"] is not None:
                worked = _working_in_24h(spans, d["first"].astimezone(timezone.utc))
                if worked > NIGHT_LIMIT:
                    w["night_over_10h"].append({"date": day.isoformat(), "working_minutes": worked})

    # A week with no working time (leave, sickness, card only showing rest) is left out of the
    # average rather than counted as zero hours.
    weekly = {k: v for k, v in weekly.items() if v["drive"] + v["work"] > 0}
    out_weeks = []
    ws = first_week
    while ws <= last_week:
        w = weekly.get(ws)
        window = [weekly[k] for k in (ws - timedelta(weeks=i) for i in range(reference_weeks)) if k in weekly]
        avg = round(sum(x["drive"] + x["work"] for x in window) / len(window)) if window else None
        working = (w["drive"] + w["work"]) if w else None
        flags = []
        if working is not None and working > WEEK_LIMIT:
            flags.append({"code": "week_over_60h", "label": "Over 60 hours' working time in the week"})
        if avg is not None and avg > AVERAGE_LIMIT and w:
            flags.append({"code": "average_over_48h", "label": f"{reference_weeks}-week average over 48 hours"})
        if w and w["night_over_10h"]:
            flags.append({"code": "night_over_10h", "label": "Over 10 hours' working time in 24 hours with night work"})
        out_weeks.append({
            "week_start": ws.isoformat(), "has_data": w is not None,
            "working_minutes": working, "drive_minutes": w["drive"] if w else None, "work_minutes": w["work"] if w else None,
            "poa_minutes": w["available"] if w else None, "night_work_days": w["night_days"] if w else 0,
            "night_over_10h": w["night_over_10h"] if w else [],
            "average_minutes": avg, "weeks_in_average": len(window), "flags": flags,
        })
        ws += timedelta(weeks=1)
    with_data = [w for w in out_weeks if w["has_data"]]
    return {
        "reference_weeks": reference_weeks,
        "weeks": list(reversed(out_weeks)),
        "latest_average_minutes": next((w["average_minutes"] for w in reversed(out_weeks) if w["average_minutes"] is not None), None),
        "max_week_minutes": max((w["working_minutes"] for w in with_data), default=None),
        "flag_count": sum(len(w["flags"]) for w in out_weeks),
        "data_from": min(days).isoformat() if days else None,
        "data_to": max(days).isoformat() if days else None,
    }


def daily_rows(spans, start: date, end: date) -> list[dict]:
    """One row per day with card activity: for payroll and working time records."""
    rows = []
    for day, d in sorted(daily(spans).items()):
        if not (start <= day <= end) or not any(d[k] for k in ("drive", "work", "available")):
            continue
        rows.append({
            "date": day.isoformat(),
            "first_activity": d["first"].strftime("%H:%M") if d["first"] else "",
            "last_activity": d["last"].strftime("%H:%M") if d["last"] else "",
            "drive_minutes": d["drive"], "other_work_minutes": d["work"], "poa_minutes": d["available"],
            "working_minutes": d["drive"] + d["work"], "night_work": d["night"],
        })
    return rows

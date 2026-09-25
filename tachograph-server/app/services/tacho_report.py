"""The weekly driver report: the per-day table an operator reviews and a driver
signs, built from a parsed driver card plus the infringements the rules engine
found.

The card records everything in UTC. Drivers' hours are judged, and reports are
read, in the local time the driver actually worked, so every time in here is
converted before the day is cut. Getting that wrong shifts activity across
midnight and moves it into the wrong day of the report.

One row is one calendar day. Some columns describe the day (driving, work,
availability, distance) and some describe the duty period the day belongs to
(shift length, daily rest, the rest before it), which is why a duty period that
runs past midnight fills those in on the day it ends.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.ddd_parser import CardIncident, VehiclePeriod
from app.services.tacho_rules import (
    Activity, DutyDay, Infringement, _duty_days, _prepare)

LOCAL = ZoneInfo("Europe/London")
WORKING_TIME_RULES = {"wtd_break", "wtd_daily_break"}
DEFAULT_RULE = "HGV EU"


def hhmm(minutes: int | None) -> str:
    """Durations print as hh:mm and run past 24h, as a shift total can."""
    if minutes is None:
        return ""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _overlap(a_start: datetime, a_end: datetime,
             b_start: datetime, b_end: datetime) -> int:
    """Minutes the two windows share."""
    start, end = max(a_start, b_start), min(a_end, b_end)
    return max(0, int((end - start).total_seconds() // 60))


def _iso_week(d: date) -> tuple[int, int]:
    y, w, _ = d.isocalendar()
    return (y, w)


def _week_start(d: date) -> date:
    return d - timedelta(days=d.isoweekday() - 1)


class _Local:
    """Cuts a UTC timeline into local calendar days."""

    def __init__(self, tz: ZoneInfo):
        self.tz = tz

    def day(self, dt: datetime) -> date:
        return dt.astimezone(self.tz).date()

    def clock(self, dt: datetime | None) -> str:
        return dt.astimezone(self.tz).strftime("%H:%M") if dt else ""

    def bounds(self, d: date) -> tuple[datetime, datetime]:
        """The UTC instants a local calendar day starts and ends at."""
        start = datetime(d.year, d.month, d.day, tzinfo=self.tz)
        return start, start + timedelta(days=1)


def _drive_by_date(acts: list[Activity], lo: _Local) -> dict[date, int]:
    """Driving minutes per local calendar day, over the whole timeline.

    Built from every activity on the card rather than from the report's own
    rows: the fortnight figure on the first Monday of a report depends on the
    week before it, which the report itself does not show.
    """
    out: dict[date, int] = {}
    for a in acts:
        if a.type != "drive":
            continue
        d = lo.day(a.start)
        while True:
            start, end = lo.bounds(d)
            mins = _overlap(a.start, a.end, start, end)
            if mins:
                out[d] = out.get(d, 0) + mins
            if end >= a.end:
                break
            d += timedelta(days=1)
    return out


def _timeline_for_day(d: date, lo: _Local, acts: list[Activity]) -> tuple[list[dict], dict[str, int]]:
    """Return clipped driver-card activity segments for one local 24-hour row."""
    day_start, day_end = lo.bounds(d)
    segments: list[dict] = []
    totals = {"drive": 0, "work": 0, "available": 0, "rest": 0}
    for activity in acts:
        start = max(activity.start, day_start)
        end = min(activity.end, day_end)
        if end <= start:
            continue
        start_minute = max(0, int((start - day_start).total_seconds() // 60))
        end_minute = min(1440, int((end - day_start).total_seconds() // 60))
        if end_minute <= start_minute:
            continue
        segments.append({"type": activity.type, "start": start_minute, "end": end_minute})
        totals[activity.type] = totals.get(activity.type, 0) + end_minute - start_minute
    return segments, totals


def _day_row(d: date, lo: _Local, acts: list[Activity], days: list[DutyDay],
             by_day: dict[date, list[VehiclePeriod]],
             covered: tuple[date, date]) -> dict:
    start, end = lo.bounds(d)
    totals = {"drive": 0, "work": 0, "available": 0, "rest": 0}
    for a in acts:
        if a.end <= start or a.start >= end:
            continue
        totals[a.type] = totals.get(a.type, 0) + _overlap(a.start, a.end, start, end)

    on_duty = [day for day in days if day.start < end and day.end > start]
    starting = next((day for day in on_duty if lo.day(day.start) == d), None)
    ending = next((day for day in on_duty if lo.day(day.end) == d), None)

    # A break is rest taken inside the duty period. Rest either side of it is
    # the daily rest, and counting that as a break would flatter the day.
    brk = 0
    for day in on_duty:
        for a in day.acts:
            if a.type == "rest":
                brk += _overlap(a.start, a.end, start, end)

    first_drive = next((a.start for a in acts
                        if a.type == "drive" and a.start < end and a.end > start), None)

    used = by_day.get(d, [])
    regs = list(dict.fromkeys(v.registration for v in used if v.registration))
    odo_start = next((v.odometer_start for v in used if v.odometer_start is not None), None)
    odo_end = next((v.odometer_end for v in reversed(used)
                    if v.odometer_end is not None), None)
    distance = sum(v.distance or 0 for v in used) or None

    # Two different figures that must never be merged, and are reported side
    # by side because an operator is asked for both:
    #
    #   shift duty   driving + other work + availability. What the driver was
    #                at work for, which is the column a signed report carries.
    #   WTD active   driving + other work only. Availability is excluded
    #                because the Working Time Regulations exclude it, and this
    #                is the figure the 6-hour break threshold is judged on.
    shift_duty = totals["drive"] + totals["work"] + totals["available"]
    wtd_active = totals["drive"] + totals["work"]
    # A duty period the data never shows the end of has no end time, no length
    # and no daily rest; the card was simply downloaded mid-shift.
    closed = ending is not None and ending.closed_by_rest
    timeline, timeline_totals = _timeline_for_day(d, lo, acts)
    return {
        "timeline": timeline,
        "timeline_totals": timeline_totals,
        "date": d.isoformat(),
        "registration": ", ".join(regs),
        "odometer_start": odo_start,
        "odometer_end": odo_end,
        "distance": distance,
        "start_duty": lo.clock(starting.start if starting else None),
        "drive_start": lo.clock(first_drive),
        "end_duty": lo.clock(ending.end if closed else None),
        "daily_rest": ending.daily_rest if closed else None,
        "drive": totals["drive"],
        "work": totals["work"],
        "poa": totals["available"],
        "break": brk,
        "shift": ending.span if closed else None,
        "shift_duty": shift_duty,
        "wtd_active": wtd_active,
        # The old name for shift duty, kept so an older page or a stored report
        # does not lose the column while both names are in circulation.
        "wtd": shift_duty,
        "previous_rest": starting.rest_before if starting else None,
        "rule": DEFAULT_RULE if on_duty else "",
        # A date the download does not reach is unknown, not a rest day. Saying
        # "Rest Day" there would assert something the card never recorded.
        "no_data": not (covered[0] <= d <= covered[1]),
        "rest_day": not on_duty and covered[0] <= d <= covered[1],
    }


def build_report(parsed: dict, infringements: list[Infringement],
                 start: date | None = None, end: date | None = None,
                 driver_ref: str | None = None, company_name: str | None = None,
                 tz: ZoneInfo = LOCAL) -> dict:
    """Assemble the report. `parsed` is a parse_driver_card() result."""
    lo = _Local(tz)
    acts = _prepare(parsed["activities"])
    days = _duty_days(acts)
    vehicles = parsed.get("vehicles") or []
    incidents: list[CardIncident] = parsed.get("incidents") or []

    if not acts:
        return {"driver": {}, "weeks": [], "period": {}}
    covered = (lo.day(acts[0].start), lo.day(acts[-1].end))
    first = start or covered[0]
    last = end or covered[1]

    # The card writes one vehicle record per spell, cut at UTC midnight, so in
    # summer a record can brush the previous local day by an hour. Each record
    # belongs to the local day it starts in, and only that one, or a day picks
    # up its neighbour's mileage.
    by_day: dict[date, list[VehiclePeriod]] = {}
    for v in vehicles:
        by_day.setdefault(lo.day(v.first_use), []).append(v)

    rows = []
    cursor = first
    while cursor <= last:
        rows.append(_day_row(cursor, lo, acts, days, by_day, covered))
        cursor += timedelta(days=1)

    # Fortnight driving is the previous fixed week plus this week so far, the
    # running figure a driver is checked against at the roadside.
    drive_by_date = _drive_by_date(acts, lo)
    week_drive: dict[tuple[int, int], int] = {}
    for d, mins in drive_by_date.items():
        wk = _iso_week(d)
        week_drive[wk] = week_drive.get(wk, 0) + mins
    for row in rows:
        d = date.fromisoformat(row["date"])
        wk = _iso_week(d)
        so_far = sum(mins for day, mins in drive_by_date.items()
                     if _iso_week(day) == wk and day <= d)
        row["fortnight_drive"] = so_far + week_drive.get(_iso_week(d - timedelta(days=7)), 0)

    weeks: list[dict] = []
    for row in rows:
        d = date.fromisoformat(row["date"])
        ws = _week_start(d)
        if not weeks or weeks[-1]["start"] != ws.isoformat():
            weeks.append({"start": ws.isoformat(),
                          "end": min(ws + timedelta(days=6), last).isoformat(),
                          "days": []})
        weeks[-1]["days"].append(row)

    for week in weeks:
        ws = date.fromisoformat(week["start"])
        we = ws + timedelta(days=7)
        week["totals"] = {
            key: sum(r[key] or 0 for r in week["days"])
            for key in ("distance", "drive", "work", "poa", "break",
                        "shift_duty", "wtd_active", "wtd")
        }
        week["totals"]["daily_rest"] = sum(r["daily_rest"] or 0 for r in week["days"])
        week["totals"]["shift"] = sum(r["shift"] or 0 for r in week["days"])

        in_week = [i for i in infringements if ws <= lo.day(i.start) < we]
        as_dict = lambda i: {                                    # noqa: E731
            "date": lo.day(i.start).isoformat(), "time": lo.clock(i.start),
            "start": i.start.isoformat(),
            "rule": i.rule, "title": i.title, "severity": i.severity,
            "detail": i.detail, "limit_minutes": i.limit_minutes,
            "actual_minutes": i.actual_minutes,
        }
        week["working_time_infringements"] = [
            as_dict(i) for i in in_week if i.rule in WORKING_TIME_RULES]
        week["infringements"] = [
            as_dict(i) for i in in_week if i.rule not in WORKING_TIME_RULES]
        week["faults"] = [{
            "date": lo.day(e.start).isoformat(), "time": lo.clock(e.start),
            "kind": e.kind, "name": e.name, "registration": e.registration,
        } for e in incidents if ws <= lo.day(e.start) < we]

    return {
        "driver": {
            "ref": driver_ref or parsed.get("driver_ref"),
            "name": parsed.get("driver_name"),
            "card_number": parsed.get("card_number"),
        },
        "company_name": company_name or parsed.get("company_name"),
        "period": {"from": first.isoformat(), "to": last.isoformat(),
                   "timezone": str(tz),
                   "data_from": covered[0].isoformat(),
                   "data_to": covered[1].isoformat()},
        "weeks": weeks,
    }

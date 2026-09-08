"""EU 561/2006 drivers' hours + Working Time Directive infringement engine.

This is a screening aid, not a legal ruling: it flags the infringements a DVSA
analysis normally raises, from a normalised activity timeline. Edge cases in the
regulation (split daily rest, ferry/train derogations, multi-manning, week-rest
compensation) are simplified and documented per rule.

Input model
-----------
A driver's timeline is a list of contiguous `Activity` spans, each one of:
  drive | work | available | rest
"drive" and "work" count as working time (WTD); "available" is period-of-
availability; "rest" is break/rest. Spans must be sorted and contiguous (the
loader fills any gap as 'rest').
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# --- limits (minutes) -------------------------------------------------------
CONT_DRIVE_MAX = 4 * 60 + 30          # 4h30 continuous driving before a break
BREAK_FULL = 45                        # qualifying break (or 15 + 30 split)
BREAK_SPLIT_FIRST = 15
BREAK_SPLIT_SECOND = 30
DAILY_DRIVE_NORMAL = 9 * 60            # 9h daily driving
DAILY_DRIVE_EXTENDED = 10 * 60         # 10h, allowed max twice a week
DAILY_DRIVE_EXTENSIONS_PER_WEEK = 2
DAILY_REST_REGULAR = 11 * 60           # 11h regular daily rest
DAILY_REST_REDUCED = 9 * 60            # 9h reduced daily rest (max 3 / week)
DAILY_REST_REDUCTIONS_PER_WEEK = 3
WEEKLY_DRIVE_MAX = 56 * 60             # 56h in a fixed week
FORTNIGHT_DRIVE_MAX = 90 * 60          # 90h across two consecutive weeks
WTD_WORK_BEFORE_BREAK = 6 * 60         # 6h working time before a break
WTD_BREAK_MIN = 30                     # >=30 min (45 if >9h worked)


@dataclass
class Activity:
    type: str
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class Infringement:
    rule: str
    title: str
    severity: str          # minor | serious | very_serious
    start: datetime
    end: datetime
    detail: str
    limit_minutes: int
    actual_minutes: int

    def to_dict(self, driver: str | None = None) -> dict:
        d = {
            "rule": self.rule, "title": self.title, "severity": self.severity,
            "start": self.start.isoformat(), "end": self.end.isoformat(),
            "detail": self.detail, "limit_minutes": self.limit_minutes,
            "actual_minutes": self.actual_minutes,
        }
        if driver is not None:
            d["driver"] = driver
        return d


# --- helpers ----------------------------------------------------------------

def _prepare(activities: list[Activity]) -> list[Activity]:
    """Sort, drop empties, and fill any time gaps between spans with 'rest'."""
    acts = sorted((a for a in activities if a.end > a.start), key=lambda a: a.start)
    filled: list[Activity] = []
    for a in acts:
        if filled and a.start > filled[-1].end:
            filled.append(Activity("rest", filled[-1].end, a.start))
        filled.append(a)
    return filled


def _iso_week(dt: datetime) -> tuple[int, int]:
    y, w, _ = dt.isocalendar()
    return (y, w)


def _duty_days(acts: list[Activity]) -> list[tuple[datetime, datetime, list[Activity]]]:
    """Split the timeline into duty days at every rest span >= reduced daily
    rest (9h). Returns (day_start, day_end, activities) for each working day."""
    days: list[tuple[datetime, datetime, list[Activity]]] = []
    cur: list[Activity] = []
    for a in acts:
        if a.type == "rest" and a.minutes >= DAILY_REST_REDUCED:
            if cur:
                days.append((cur[0].start, cur[-1].end, cur))
                cur = []
            continue
        cur.append(a)
    if cur:
        days.append((cur[0].start, cur[-1].end, cur))
    return days


# --- individual rules -------------------------------------------------------

def check_continuous_driving(acts: list[Activity]) -> list[Infringement]:
    """>4h30 driving without a 45-min break (or 15+30 split)."""
    out: list[Infringement] = []
    drive = 0
    break_first = 0      # a >=15 min break seen
    break_accum = 0      # running non-driving minutes toward a break
    seg_start: datetime | None = None
    seg_end: datetime | None = None
    for a in acts:
        if a.type == "drive":
            if seg_start is None:
                seg_start = a.start
            seg_end = a.end
            drive += a.minutes
            break_accum = 0
            if drive > CONT_DRIVE_MAX:
                out.append(Infringement(
                    "continuous_driving", "Driving over 4h30 without a break",
                    "serious" if drive <= CONT_DRIVE_MAX + 30 else "very_serious",
                    seg_start, seg_end,
                    f"{drive} min continuous driving before a qualifying break.",
                    CONT_DRIVE_MAX, drive))
                drive = 0
                break_first = 0
                seg_start = None
        else:
            # accumulate a potential break
            span = a.minutes
            if span >= BREAK_FULL:
                drive = 0
                break_first = 0
                seg_start = None
            elif span >= BREAK_SPLIT_FIRST and span < BREAK_SPLIT_SECOND:
                break_first = span
            elif span >= BREAK_SPLIT_SECOND:
                if break_first >= BREAK_SPLIT_FIRST:  # 15 then 30 => valid split
                    drive = 0
                    break_first = 0
                    seg_start = None
                else:
                    break_first = span
    return out


def check_daily(acts: list[Activity]) -> list[Infringement]:
    """Per-day driving (>9h/>10h) and daily rest (<11h / <9h) rules."""
    out: list[Infringement] = []
    days = _duty_days(acts)
    ext_by_week: dict[tuple[int, int], int] = {}
    red_by_week: dict[tuple[int, int], int] = {}
    for i, (start, end, day_acts) in enumerate(days):
        drive = sum(a.minutes for a in day_acts if a.type == "drive")
        wk = _iso_week(start)
        if drive > DAILY_DRIVE_EXTENDED:
            out.append(Infringement(
                "daily_driving", "Daily driving over 10h", "very_serious",
                start, end, f"{drive} min driving in the day (limit {DAILY_DRIVE_EXTENDED}).",
                DAILY_DRIVE_EXTENDED, drive))
        elif drive > DAILY_DRIVE_NORMAL:
            ext_by_week[wk] = ext_by_week.get(wk, 0) + 1
            if ext_by_week[wk] > DAILY_DRIVE_EXTENSIONS_PER_WEEK:
                out.append(Infringement(
                    "daily_driving_extension", "More than two 10h driving days in the week",
                    "serious", start, end,
                    f"{drive} min driving; a 3rd+ extended (9-10h) day this week.",
                    DAILY_DRIVE_NORMAL, drive))

        # 24-hour rule: a daily rest must START within 24h of the duty day
        # starting (i.e. of the previous daily rest ending). The duty-day working
        # span is start..end; the next daily rest begins at `end`.
        duty_span = int((end - start).total_seconds() // 60)
        if duty_span > 24 * 60:
            out.append(Infringement(
                "daily_rest_24h", "Daily rest not taken within 24 hours", "very_serious",
                start, end, f"{duty_span} min from duty start to the next daily rest (limit {24 * 60}).",
                24 * 60, duty_span))

        # Reduced daily rest (9-11h) is allowed at most 3 times between weekly
        # rests; the rest that split this day from the next is days[i+1].start - end.
        if i + 1 < len(days):
            rest = int((days[i + 1][0] - end).total_seconds() // 60)
            if DAILY_REST_REDUCED <= rest < DAILY_REST_REGULAR:
                red_by_week[wk] = red_by_week.get(wk, 0) + 1
                if red_by_week[wk] > DAILY_REST_REDUCTIONS_PER_WEEK:
                    out.append(Infringement(
                        "daily_rest_reduction", "More than three reduced daily rests in the week",
                        "serious", end, days[i + 1][0],
                        f"{rest} min rest; a 4th+ reduced (9-11h) rest this week.",
                        DAILY_REST_REGULAR, rest))
    return out


def check_weekly_driving(acts: list[Activity]) -> list[Infringement]:
    """>56h in a fixed (ISO) week, and >90h over two consecutive weeks."""
    out: list[Infringement] = []
    per_week: dict[tuple[int, int], int] = {}
    span_by_week: dict[tuple[int, int], tuple[datetime, datetime]] = {}
    for a in acts:
        if a.type == "drive":
            wk = _iso_week(a.start)
            per_week[wk] = per_week.get(wk, 0) + a.minutes
            s, e = span_by_week.get(wk, (a.start, a.end))
            span_by_week[wk] = (min(s, a.start), max(e, a.end))
    for wk, mins in per_week.items():
        if mins > WEEKLY_DRIVE_MAX:
            s, e = span_by_week[wk]
            out.append(Infringement(
                "weekly_driving", "Weekly driving over 56h", "serious",
                s, e, f"{mins} min driving in week {wk[1]}/{wk[0]} (limit {WEEKLY_DRIVE_MAX}).",
                WEEKLY_DRIVE_MAX, mins))
    weeks = sorted(per_week)
    for a, b in zip(weeks, weeks[1:]):
        if b[1] - a[1] == 1 or (a[1] >= 52 and b[1] == 1):  # consecutive
            total = per_week[a] + per_week[b]
            if total > FORTNIGHT_DRIVE_MAX:
                s = span_by_week[a][0]
                e = span_by_week[b][1]
                out.append(Infringement(
                    "fortnightly_driving", "Two-week driving over 90h", "serious",
                    s, e, f"{total} min driving across weeks {a[1]} and {b[1]} (limit {FORTNIGHT_DRIVE_MAX}).",
                    FORTNIGHT_DRIVE_MAX, total))
    return out


def check_wtd_break(acts: list[Activity]) -> list[Infringement]:
    """WTD: a break is due once working time (drive+work) reaches 6h."""
    out: list[Infringement] = []
    work = 0
    seg_start: datetime | None = None
    seg_end: datetime | None = None
    for a in acts:
        if a.type in ("drive", "work"):
            if seg_start is None:
                seg_start = a.start
            seg_end = a.end
            work += a.minutes
            if work > WTD_WORK_BEFORE_BREAK:
                out.append(Infringement(
                    "wtd_break", "Over 6h working time without a break", "serious",
                    seg_start, seg_end, f"{work} min working time before a 30-min break.",
                    WTD_WORK_BEFORE_BREAK, work))
                work = 0
                seg_start = None
        elif a.minutes >= WTD_BREAK_MIN:
            work = 0
            seg_start = None
    return out


ALL_RULES = [
    check_continuous_driving,
    check_daily,
    check_weekly_driving,
    check_wtd_break,
]


def analyse(activities: list[Activity]) -> list[Infringement]:
    """Run every rule over one driver's timeline, newest first."""
    acts = _prepare(activities)
    found: list[Infringement] = []
    for rule in ALL_RULES:
        found.extend(rule(acts))
    found.sort(key=lambda i: i.start, reverse=True)
    return found

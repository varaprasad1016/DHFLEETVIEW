"""EU 561/2006 drivers' hours + Working Time Directive infringement engine.

This is a screening aid, not a legal ruling: it flags the infringements a DVSA
analysis normally raises, from a normalised activity timeline.

Split daily rest, multi-manning and weekly-rest compensation are all handled.
Multi-manning is taken from the card's own slot records; where the reader
cannot tell which slot was used, a rest that is short for one driver but legal
for a crew is raised as something to confirm rather than as an infringement.
Ferry and train derogations remain simplified and are documented per rule.

Input model
-----------
A driver's timeline is a list of contiguous `Activity` spans, each one of:
  drive | work | available | rest
"drive" and "work" count as working time (WTD); "available" is period-of-
availability; "rest" is break/rest. Spans must be sorted and contiguous (the
loader fills any gap as 'rest'), and adjacent spans of the same type are merged,
so a rest that runs across midnight is one span and not two.

Duty days
---------
A "day" here is the duty period between two daily rests, which is what 561/2006
actually regulates, not a calendar day. It can span more than one date when the
driver never took a qualifying daily rest.

Severity
--------
Bands follow Directive (EU) 2016/403 Annex I, the minor / serious / very serious
table DVSA works to. Working-time (RTD) breaches are not in that Annex, so they
are banded on the size of the overrun and that is documented at the rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

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
# A regular daily rest may be taken in two pieces instead of one: at least 3
# hours uninterrupted, then at least 9 hours uninterrupted, 12 hours in all.
# Both pieces must fall in the 24 hours from the start of the duty period.
DAILY_REST_SPLIT_FIRST = 3 * 60
DAILY_REST_SPLIT_SECOND = 9 * 60
DAILY_REST_SPLIT_TOTAL = 12 * 60
DAILY_REST_CANDIDATE = 3 * 60          # shortest stop treated as an attempted
                                       # daily rest when none reaches 9h
DUTY_DAY_MAX = 24 * 60                 # a daily rest must start within 24h
# Multi-manning: with a second driver aboard the rest is 9 hours taken inside
# 30, rather than 11 inside 24. Judging a two-up shift by the single-driver
# rule reports a perfectly legal crew change as an insufficient daily rest.
MULTI_MANNED_WINDOW = 30 * 60
MULTI_MANNED_REST = 9 * 60
WEEKLY_REST_REDUCED = 24 * 60          # >= 24h counts as a weekly rest
WEEKLY_REST_REGULAR = 45 * 60
WEEKLY_PERIOD_MAX = 6 * 24 * 60        # six 24h periods between weekly rests
WEEKLY_DRIVE_MAX = 56 * 60             # 56h in a fixed week
FORTNIGHT_DRIVE_MAX = 90 * 60          # 90h across two consecutive weeks
WTD_WORK_BEFORE_BREAK = 6 * 60         # 6h working time before a break
WTD_PAUSE_UNIT = 15                    # a pause counts once it reaches 15 min
WTD_BREAK_MIN = 30                     # >= 30 min of pause up to 9h worked
WTD_BREAK_LONG = 45                    # >= 45 min of pause over 9h worked
WTD_LONG_DAY = 9 * 60


@dataclass
class Activity:
    type: str
    start: datetime
    end: datetime
    # True where the card was in the second slot, i.e. the holder was crewing
    # as co-driver. Multi-manned work is rested differently - 9 hours inside 30
    # rather than 11 inside 24 - so a rule that cannot see this reports a
    # perfectly legal two-up shift as an insufficient daily rest.
    crew: bool = False

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class PlaceEntry:
    """A place the driver entered at the start or end of a daily work period.

    ``country`` is the legacy NationNumeric value used by the Gen1 reader.
    ``country_name`` lets the Go reader preserve its richer enum/string value;
    the compliance rule considers either representation a valid entry.
    """
    time: datetime
    kind: str              # begin | end
    country: int = 0       # NationNumeric; 0 means nothing was entered
    country_name: str = ""

    @property
    def has_country(self) -> bool:
        return (self.country not in (0x00, 0xFD, 0xFE, 0xFF)
                or bool(self.country_name))


@dataclass
class CardGap:
    """A period the card spent out of a tachograph."""
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


# The short code each rule is cited by on a printed register, alongside our own
# descriptive name. Grouped the way the regulation is: driving limits, breaks,
# rest, weekly limits, working time, and record keeping.
RULE_CODES = {
    "continuous_driving":     "EU-BRK-01",
    "daily_driving":          "EU-DRV-01",
    "daily_driving_extension": "EU-DRV-02",
    "weekly_driving":         "EU-DRV-03",
    "fortnightly_driving":    "EU-DRV-04",
    "daily_rest_short":       "EU-RST-01",
    "daily_rest_24h":         "EU-RST-02",
    "daily_rest_reduction":   "EU-RST-03",
    "weekly_rest_period":     "EU-RST-04",
    "weekly_rest_compensation": "EU-COMP-01",
    "wtd_break":              "WTD-BRK-01",
    "wtd_daily_break":        "WTD-BRK-02",
    "country_start":          "REC-01",
    "country_end":            "REC-02",
    "card_withdrawal":        "REC-03",
    # Not a breach: a shift that may have been crewed, which somebody has to
    # confirm before it is judged either way.
    "multi_manning_unverified": "CREW-01",
}


def code_for(rule: str) -> str:
    """The register code for a rule, or the rule's own name if it has none."""
    return RULE_CODES.get(rule, rule.upper().replace("_", "-"))


@dataclass
class Infringement:
    rule: str
    title: str
    severity: str          # minor | serious | very_serious
    start: datetime
    end: datetime
    detail: str
    # A record-keeping rule has no duration limit to quote, so both are None.
    limit_minutes: int | None
    actual_minutes: int | None

    def to_dict(self, driver: str | None = None) -> dict:
        d = {
            "rule": self.rule, "code": code_for(self.rule),
            "title": self.title, "severity": self.severity,
            "start": self.start.isoformat(), "end": self.end.isoformat(),
            "detail": self.detail, "limit_minutes": self.limit_minutes,
            "actual_minutes": self.actual_minutes,
        }
        if driver is not None:
            d["driver"] = driver
        return d


@dataclass
class DutyDay:
    """One duty period between two daily rests."""
    start: datetime
    end: datetime
    acts: list[Activity] = field(default_factory=list)
    rest_after: int | None = None        # minutes of rest that closed the day
    rest_start: datetime | None = None
    rest_end: datetime | None = None
    closed_by_rest: bool = False         # False when the timeline just ran out
    rest_before: int | None = None       # the rest this day started from
    rest_before_end: datetime | None = None

    @property
    def span(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)

    @property
    def drive(self) -> int:
        return sum(a.minutes for a in self.acts if a.type == "drive")

    @property
    def working_time(self) -> int:
        return sum(a.minutes for a in self.acts if a.type in ("drive", "work"))

    @property
    def daily_rest(self) -> int | None:
        """The rest that counts as this day's daily rest.

        561/2006 requires the rest to be taken within the 24 hours that begin
        when the duty period starts, so only the part of the rest falling inside
        that window counts. A driver who starts at 05:31, finishes at 18:32 and
        starts again at 05:34 has rested 11h02 but only 10h59 of it lands in the
        24-hour period, which makes it a reduced rest rather than a regular one.
        That is how an analyser scores it, and it is what decides whether the
        driver has used up their three reductions.
        """
        # With a second driver aboard the window is 30 hours, not 24.
        return self.rest_within(self.rest_window)

    def rest_within(self, window: int) -> int | None:
        """How much of the closing rest lands inside a window of this length.

        Separated out so the same question can be asked of a window the driver
        may or may not have been entitled to - which is what decides whether an
        unverified shift could legitimately have been crewed.
        """
        if self.rest_after is None or self.rest_start is None:
            return None
        if self.span > window:
            return self.rest_after          # already flagged by the window rule
        window_end = self.start + timedelta(minutes=window)
        room = int((window_end - self.rest_start).total_seconds() // 60)
        return max(0, min(self.rest_after, room))

    @property
    def crewed(self) -> bool:
        """Whether this duty period was worked with a second driver aboard.

        Taken from the card's own slot records, which is the only verified
        source: anything else is a guess about who else was in the cab.
        """
        return any(a.crew for a in self.acts)

    @property
    def crewing(self) -> str:
        """single | multi — what the card actually shows."""
        return "multi" if self.crewed else "single"

    @property
    def rest_window(self) -> int:
        """How long the driver has to get their daily rest taken."""
        return MULTI_MANNED_WINDOW if self.crewed else DUTY_DAY_MAX

    @property
    def rest_needed(self) -> int:
        """The shortest daily rest that is not a reduction."""
        return MULTI_MANNED_REST if self.crewed else DAILY_REST_REGULAR

    @property
    def split_first(self) -> int | None:
        """The opening half of a split daily rest, if the driver took one.

        A regular daily rest may be split in two: at least 3 hours
        uninterrupted, then at least 9 hours, 12 hours in all. The first piece
        sits inside the duty period rather than closing it, so a rule that only
        looks at the rest which ended the day cannot see it - and scores a
        perfectly legal split rest as a reduced one, spending one of the three
        reductions the driver is allowed between weekly rests.

        The longest single stop is used: the pieces must each be uninterrupted,
        so two short stops cannot be added together to make three hours.
        """
        longest = max((a.minutes for a in self.acts if a.type == "rest"), default=0)
        return longest if longest >= DAILY_REST_SPLIT_FIRST else None

    @property
    def rest_kind(self) -> str:
        """How this day's daily rest scores: regular | split | reduced | short.

        "split" is a regular rest taken in two pieces - it is compliant and,
        importantly, costs the driver none of their reductions.
        """
        rest = self.daily_rest
        if rest is None:
            return "none"
        if rest >= self.rest_needed:
            return "regular"
        first = self.split_first
        if (first is not None and rest >= DAILY_REST_SPLIT_SECOND
                and first + rest >= DAILY_REST_SPLIT_TOTAL):
            return "split"
        if rest >= DAILY_REST_REDUCED:
            return "reduced"
        return "short"


# --- helpers ----------------------------------------------------------------

def _hm(minutes: int) -> str:
    return f"{minutes // 60}h{minutes % 60:02d}"


def _over(actual: int, serious_at: int, very_at: int) -> str:
    """Severity for exceeding a limit."""
    if actual >= very_at:
        return "very_serious"
    if actual >= serious_at:
        return "serious"
    return "minor"


def _under(actual: int, serious_below: int, very_below: int) -> str:
    """Severity for falling short of a required rest or break."""
    if actual < very_below:
        return "very_serious"
    if actual < serious_below:
        return "serious"
    return "minor"


def _prepare(activities: list[Activity]) -> list[Activity]:
    """Sort, drop empties, fill gaps with 'rest', and merge adjacent spans of
    the same type.

    Merging is essential. A driver card stores one record per calendar day, so
    an overnight rest arrives as two spans: evening to midnight, then midnight
    to morning. Left unmerged an 11h rest looks like two ~5h rests, and no rule
    needing a qualifying rest or break would ever see one.
    """
    acts = sorted((a for a in activities if a.end > a.start), key=lambda a: a.start)
    merged: list[Activity] = []
    for a in acts:
        if merged and a.start > merged[-1].end:
            if merged[-1].type == "rest":
                merged[-1] = Activity("rest", merged[-1].start, a.start,
                                      crew=merged[-1].crew)
            else:
                merged.append(Activity("rest", merged[-1].end, a.start))
        # Spans only merge when they are the same activity *and* the same
        # crewing, so a driver who takes over the wheel mid-shift keeps the
        # boundary that says where two-up working stopped.
        if (merged and merged[-1].type == a.type and a.start <= merged[-1].end
                and merged[-1].crew == a.crew):
            merged[-1] = Activity(a.type, merged[-1].start,
                                  max(merged[-1].end, a.end), crew=a.crew)
        else:
            merged.append(a)
    return merged


def _iso_week(dt: datetime) -> tuple[int, int]:
    y, w, _ = dt.isocalendar()
    return (y, w)


def _split_overlong(block: list[Activity]) -> list[list[Activity]]:
    """Break up a duty period that runs past 24h without a qualifying daily rest.

    561/2006 measures driving between two daily rests, so a block with no 9h
    rest legitimately spans several dates: that is what an analyser reports as
    "driving time between two daily rest periods". But if the driver did stop
    for a few hours, that stop is the daily rest they attempted and the duty
    period ends there, with the rest then reported as too short. A block with no
    stop at all of 3h or more is left whole, for the 24h rule to flag.
    """
    if not block:
        return []
    span = (block[-1].end - block[0].start).total_seconds() // 60
    if span <= DUTY_DAY_MAX:
        return [block]
    candidates = [(i, a) for i, a in enumerate(block)
                  if i > 0 and a.type == "rest" and a.minutes >= DAILY_REST_CANDIDATE]
    if not candidates:
        return [block]
    i, _ = max(candidates, key=lambda t: t[1].minutes)
    return [block[:i]] + _split_overlong(block[i:])


def _duty_days(acts: list[Activity]) -> list[DutyDay]:
    """Split the timeline into duty days at every rest of 9h or more, then break
    up any remaining period that still runs past 24h."""
    blocks: list[list[Activity]] = []
    closers: list[Activity | None] = []
    openers: list[Activity | None] = []
    cur: list[Activity] = []
    pending: Activity | None = None      # the rest the next block starts from
    for a in acts:
        if a.type == "rest" and a.minutes >= DAILY_REST_REDUCED:
            if cur:
                blocks.append(cur)
                closers.append(a)
                openers.append(pending)
                cur = []
            pending = a
            continue
        cur.append(a)
    if cur:
        blocks.append(cur)
        closers.append(None)
        openers.append(pending)

    days: list[DutyDay] = []
    for block, closing, opening in zip(blocks, closers, openers):
        parts = _split_overlong(block)
        for n, part in enumerate(parts):
            # A part after the first opens with the rest that ended the previous
            # part; that rest belongs to the previous day, not to this one.
            body = part[1:] if n > 0 and part and part[0].type == "rest" else part
            if not body:
                continue
            if n + 1 < len(parts):
                nxt = parts[n + 1][0]
                rest, r_start, r_end, closed = nxt.minutes, nxt.start, nxt.end, True
            elif closing is not None:
                rest, r_start, r_end, closed = (
                    closing.minutes, closing.start, closing.end, True)
            else:
                rest = r_start = r_end = None
                closed = False
            before = part[0] if n > 0 and part and part[0].type == "rest" else opening
            days.append(DutyDay(body[0].start, body[-1].end, body,
                                rest, r_start, r_end, closed,
                                before.minutes if before else None,
                                before.end if before else None))
    return days


# --- individual rules -------------------------------------------------------

def check_continuous_driving(acts: list[Activity]) -> list[Infringement]:
    """More than 4h30 driving without a 45-minute break, or a 15-then-30 split.

    Rest and period-of-availability both count towards a break; other work does
    not, so it interrupts one. The whole continuous run is reported, which is
    how an analyser words it: "continuous driving time is 4:37 h".
    """
    out: list[Infringement] = []
    state: dict = {"drive": 0, "start": None, "end": None}
    had_15 = False
    pause = 0

    def flush() -> None:
        drive = state["drive"]
        if drive > CONT_DRIVE_MAX and state["start"] and state["end"]:
            out.append(Infringement(
                "continuous_driving", "Driving over 4h30 without a break",
                _over(drive, 5 * 60, 6 * 60), state["start"], state["end"],
                f"{_hm(drive)} of continuous driving before a qualifying break "
                f"(limit {_hm(CONT_DRIVE_MAX)}).",
                CONT_DRIVE_MAX, drive))
        state["drive"] = 0
        state["start"] = None
        state["end"] = None

    for a in acts:
        if a.type in ("rest", "available"):
            pause += a.minutes
            continue
        if pause:
            if pause >= BREAK_FULL or (pause >= BREAK_SPLIT_SECOND and had_15):
                flush()
                had_15 = False
            elif pause >= BREAK_SPLIT_FIRST:
                had_15 = True
            pause = 0
        if a.type == "drive":
            if state["start"] is None:
                state["start"] = a.start
            state["end"] = a.end
            state["drive"] += a.minutes
    flush()
    return out


def check_daily_driving(days: list[DutyDay]) -> list[Infringement]:
    """Driving between two daily rests: 9h, extendable to 10h twice a week."""
    out: list[Infringement] = []
    ext_by_week: dict[tuple[int, int], int] = {}
    for day in days:
        drive = day.drive
        wk = _iso_week(day.start)
        if drive > DAILY_DRIVE_NORMAL:
            ext_by_week[wk] = ext_by_week.get(wk, 0) + 1
        multi_day = day.start.date() != day.end.date()
        where = (f" between the daily rests of {day.start:%d/%m %H:%M} and "
                 f"{day.end:%d/%m %H:%M}") if multi_day else ""
        if drive > DAILY_DRIVE_EXTENDED:
            out.append(Infringement(
                "daily_driving", "Daily driving over 10h",
                _over(drive, 11 * 60, 12 * 60), day.start, day.end,
                f"{_hm(drive)} of driving{where} (limit {_hm(DAILY_DRIVE_EXTENDED)}).",
                DAILY_DRIVE_EXTENDED, drive))
        elif drive > DAILY_DRIVE_NORMAL and ext_by_week[wk] > DAILY_DRIVE_EXTENSIONS_PER_WEEK:
            out.append(Infringement(
                "daily_driving_extension", "More than two 10h driving days in the week",
                _over(drive, 10 * 60, 11 * 60), day.start, day.end,
                f"{_hm(drive)} of driving; extended day no. {ext_by_week[wk]} this week, "
                f"when only {DAILY_DRIVE_EXTENSIONS_PER_WEEK} are allowed.",
                DAILY_DRIVE_NORMAL, drive))
    return out


def check_daily_rest(days: list[DutyDay],
                     unverified_crew: bool = False) -> list[Infringement]:
    """Daily rest: 11h regular, or 9h reduced at most three times between weekly
    rests, and a daily rest must begin within 24h of the duty period starting."""
    out: list[Infringement] = []
    reductions = 0            # since the last weekly rest
    for day in days:
        window = day.rest_window
        if day.span > window:
            over = day.span - window
            crew = " (multi-manned)" if day.crewed else ""
            out.append(Infringement(
                "daily_rest_24h",
                f"Daily rest not taken within {window // 60} hours",
                _over(over, 3 * 60, 12 * 60), day.start, day.end,
                f"{_hm(day.span)} of duty from {day.start:%d/%m %H:%M} with no daily "
                f"rest{crew}; one is due within {_hm(window)}.",
                window, day.span))
            # Each whole window that passed without a rest is a daily rest the
            # driver never took, so it spends the weekly reduction allowance
            # just as a short rest does.
            reductions += day.span // window

        if not day.closed_by_rest or day.rest_after is None:
            continue
        if day.rest_after >= WEEKLY_REST_REDUCED:
            reductions = 0            # a weekly rest resets the reduction count
            continue
        rest = day.daily_rest
        if rest is None:
            continue
        also = ("" if rest == day.rest_after
                else f" (of {_hm(day.rest_after)} rest taken in all)")
        # A regular rest taken in two pieces is compliant and spends none of
        # the driver's three reductions, so it is settled before anything else.
        if day.rest_kind == "split":
            continue
        if rest < DAILY_REST_REDUCED:
            # A shift that may have been two-up, with nothing on the card to
            # settle it, is not called an infringement: 9 hours inside 30 is
            # legal for a crew, and accusing a driver on a guess is worse than
            # asking somebody to check.
            # Judged against the window a crew would have had, not the one a
            # single driver gets - otherwise a shift that is perfectly legal
            # two-up is still called an infringement.
            as_crew = day.rest_within(MULTI_MANNED_WINDOW) or 0
            if unverified_crew and as_crew >= MULTI_MANNED_REST:
                out.append(Infringement(
                    "multi_manning_unverified",
                    "Potential multi-manning — verification required",
                    "minor", day.rest_start, day.rest_end,
                    f"only {_hm(rest)} of daily rest{also} from "
                    f"{day.start:%d/%m %H:%M} ({_hm(as_crew)} inside the 30 hours a "
                    f"crew is allowed), which is short for a single driver but "
                    f"allowed with a second driver aboard. The card does not record "
                    f"which slot was used, so the crewing needs confirming before "
                    f"this is treated either way.",
                    DAILY_REST_REGULAR, rest))
                continue
            out.append(Infringement(
                "daily_rest_short", "Daily rest under 9h",
                _under(rest, 8 * 60, 7 * 60), day.rest_start, day.rest_end,
                f"only {_hm(rest)} of daily rest{also} in the {_hm(day.rest_window)} from "
                f"{day.start:%d/%m %H:%M}; the minimum is {_hm(DAILY_REST_REDUCED)}.",
                DAILY_REST_REDUCED, rest))
            reductions += 1
        elif rest < day.rest_needed:
            reductions += 1
            if reductions > DAILY_REST_REDUCTIONS_PER_WEEK:
                out.append(Infringement(
                    "daily_rest_reduction", "More than three reduced daily rests in the week",
                    _under(rest, 10 * 60, 8 * 60 + 30), day.rest_start, day.rest_end,
                    f"{_hm(rest)} of rest{also}; reduced or missed daily rest no. "
                    f"{reductions} since the last weekly rest, when only "
                    f"{DAILY_REST_REDUCTIONS_PER_WEEK} reductions are allowed.",
                    DAILY_REST_REGULAR, rest))
    return out


def check_weekly_rest(days: list[DutyDay]) -> list[Infringement]:
    """A weekly rest must start no later than six 24-hour periods after the end
    of the previous one. Only evaluated between two weekly rests that are both
    inside the data, so a partial download cannot raise a false positive."""
    out: list[Infringement] = []
    prev_end: datetime | None = None
    # The timeline may open part way through a week, on the back of a weekly
    # rest that closed no duty day in the data. That rest still starts the clock.
    if days and days[0].rest_before and days[0].rest_before >= WEEKLY_REST_REDUCED:
        prev_end = days[0].rest_before_end
    for day in days:
        if not (day.closed_by_rest and day.rest_after
                and day.rest_after >= WEEKLY_REST_REDUCED):
            continue
        if prev_end is not None and day.rest_start is not None:
            period = int((day.rest_start - prev_end).total_seconds() // 60)
            if period > WEEKLY_PERIOD_MAX:
                # Date it to the moment the six 24-hour periods ran out, not to
                # the weekly rest that eventually followed: that is the day the
                # driver went over, and it is where an analyser reports it.
                breached = prev_end + timedelta(minutes=WEEKLY_PERIOD_MAX)
                out.append(Infringement(
                    "weekly_rest_period", "Weekly rest not taken within six 24-hour periods",
                    _over(period - WEEKLY_PERIOD_MAX, 3 * 60, 12 * 60),
                    breached, day.rest_start,
                    f"{_hm(period)} of duty between weekly rests "
                    f"(limit {_hm(WEEKLY_PERIOD_MAX)}).",
                    WEEKLY_PERIOD_MAX, period))
        prev_end = day.rest_end
    return out


def check_weekly_driving(acts: list[Activity]) -> list[Infringement]:
    """More than 56h in a fixed (ISO) week, or 90h over two consecutive weeks."""
    out: list[Infringement] = []
    per_week: dict[tuple[int, int], int] = {}
    span_by_week: dict[tuple[int, int], tuple[datetime, datetime]] = {}
    for a in acts:
        if a.type == "drive":
            wk = _iso_week(a.start)
            per_week[wk] = per_week.get(wk, 0) + a.minutes
            s, e = span_by_week.get(wk, (a.start, a.end))
            span_by_week[wk] = (min(s, a.start), max(e, a.end))
    for wk, mins in sorted(per_week.items()):
        if mins > WEEKLY_DRIVE_MAX:
            s, e = span_by_week[wk]
            out.append(Infringement(
                "weekly_driving", "Weekly driving over 56h",
                _over(mins, 60 * 60, 70 * 60), s, e,
                f"{_hm(mins)} of driving in week {wk[1]}/{wk[0]} "
                f"(limit {_hm(WEEKLY_DRIVE_MAX)}).",
                WEEKLY_DRIVE_MAX, mins))
    weeks = sorted(per_week)
    for a, b in zip(weeks, weeks[1:]):
        if b[1] - a[1] == 1 or (a[1] >= 52 and b[1] == 1):  # consecutive
            total = per_week[a] + per_week[b]
            if total > FORTNIGHT_DRIVE_MAX:
                out.append(Infringement(
                    "fortnightly_driving", "Two-week driving over 90h",
                    _over(total, 100 * 60, 112 * 60 + 30),
                    span_by_week[a][0], span_by_week[b][1],
                    f"{_hm(total)} of driving across weeks {a[1]} and {b[1]} "
                    f"(limit {_hm(FORTNIGHT_DRIVE_MAX)}).",
                    FORTNIGHT_DRIVE_MAX, total))
    return out


def check_wtd(days: list[DutyDay]) -> list[Infringement]:
    """Working Time (RTD) breaks, per duty period.

    Working time is driving plus other work; rest and period-of-availability are
    not working time, and a pause counts once it reaches 15 minutes. Two
    separate duties: no more than 6h worked before a pause, and 30 minutes of
    pause in total across the duty, 45 minutes once more than 9h is worked.
    These are national rules and not in the Annex I severity table, so they are
    banded on the size of the overrun.
    """
    out: list[Infringement] = []
    for day in days:
        worked = 0
        pause = 0
        total_pause = 0
        seg_start: datetime | None = None
        seg_end: datetime | None = None
        for a in day.acts:
            if a.type in ("rest", "available"):
                pause += a.minutes
                continue
            if pause:
                if pause >= WTD_PAUSE_UNIT:
                    total_pause += pause
                    worked = 0
                    seg_start = None
                pause = 0
            if seg_start is None:
                seg_start = a.start
            seg_end = a.end
            worked += a.minutes
            if worked > WTD_WORK_BEFORE_BREAK:
                out.append(Infringement(
                    "wtd_break", "Over 6h working time without a break",
                    _over(worked - WTD_WORK_BEFORE_BREAK, 60, 3 * 60), seg_start, seg_end,
                    f"{_hm(worked)} of working time before a {WTD_PAUSE_UNIT}-minute pause "
                    f"(limit {_hm(WTD_WORK_BEFORE_BREAK)}).",
                    WTD_WORK_BEFORE_BREAK, worked))
                worked = 0
                seg_start = None
        if pause >= WTD_PAUSE_UNIT:
            total_pause += pause

        wt = day.working_time
        required = (WTD_BREAK_LONG if wt > WTD_LONG_DAY
                    else WTD_BREAK_MIN if wt > WTD_WORK_BEFORE_BREAK else 0)
        if required and total_pause < required:
            out.append(Infringement(
                "wtd_daily_break", "Too little break in the working day",
                _over(required - total_pause, 15, 30), day.start, day.end,
                f"{_hm(total_pause)} of pause taken in {_hm(wt)} of working time, "
                f"when at least {required} minutes is required.",
                required, total_pause))
    return out


def check_country_entries(days: list[DutyDay],
                          places: list[PlaceEntry]) -> list[Infringement]:
    """The driver must enter the country at the start and the end of each daily
    work period. Annex I treats a missing symbol as a minor infringement.

    An entry made a little before the first activity still counts: the driver
    types it as the card goes in, which the card timestamps ahead of the first
    activity change.
    """
    out: list[Infringement] = []
    begins = [p for p in places if p.kind == "begin" and p.has_country]
    ends = [p for p in places if p.kind == "end" and p.has_country]
    early = timedelta(hours=2)
    for day in days:
        if not any(day.start - early <= p.time <= day.end for p in begins):
            out.append(Infringement(
                "country_start", "No country entered at the start of work",
                "minor", day.start, day.start,
                f"no country was entered when the duty period beginning "
                f"{day.start:%d/%m %H:%M} started.", None, None))
        # Only judge the end of a day the data actually shows the end of.
        if day.closed_by_rest and not any(day.start <= p.time <= day.end + early for p in ends):
            out.append(Infringement(
                "country_end", "No country entered at the end of work",
                "minor", day.end, day.end,
                f"no country was entered when the duty period ending "
                f"{day.end:%d/%m %H:%M} finished.", None, None))
    return out


def check_card_withdrawal(days: list[DutyDay], gaps: list[CardGap],
                          places: list[PlaceEntry]) -> list[Infringement]:
    """The card coming out mid-duty without the driver closing off the work
    period: no end-of-work entry was made, so nothing records what the driver
    did next.

    A card that comes out with an end-of-work entry against it is a normal sign
    off, and a brief withdrawal is how a driver moves between vehicles, so
    neither is reported. This is not an Annex I item; it is banded on how long
    the card stayed out.
    """
    out: list[Infringement] = []
    ends = [p for p in places if p.kind == "end"]
    window = timedelta(minutes=30)
    for gap in gaps:
        if gap.minutes < 15:
            continue                       # swapping vehicles, not signing off
        if any(abs(p.time - gap.start) <= window for p in ends):
            continue                       # the driver did close the day off
        day = next((d for d in days if d.start < gap.start < d.end), None)
        if day is None:
            continue                       # came out between duty periods
        left = int((day.end - gap.start).total_seconds() // 60)
        out.append(Infringement(
            "card_withdrawal", "Card withdrawn before the end of the working day",
            "serious" if gap.minutes >= 60 else "minor", gap.start, gap.end,
            f"the card was out of a tachograph for {_hm(gap.minutes)} from "
            f"{gap.start:%d/%m %H:%M} with no end-of-work entry, while the duty period "
            f"still had {_hm(left)} to run.", None, gap.minutes))
    return out


def check_weekly_compensation(days: list[DutyDay]) -> list[Infringement]:
    """A reduced weekly rest that was never paid back in time.

    Nothing is raised while the debt is still inside its window: carrying one
    is ordinary, and flagging it would teach an operator to ignore the warning.
    Only a window that closed with the debt still open is a breach - and only
    when the data runs far enough past the deadline to say so.
    """
    from app.services import weekly_compensation as comp

    rests = comp.rests_from_days(days)
    if not rests:
        return []
    ends = max(day.end for day in days).date()
    _ledger, breaches = comp.build(rests, data_ends=ends)

    out: list[Infringement] = []
    for breach in breaches:
        debt = breach["debt"]
        taken = datetime.fromisoformat(debt["taken_at"])
        short = debt["deficit_minutes"]
        out.append(Infringement(
            "weekly_rest_compensation",
            "Reduced weekly rest never paid back",
            _under(comp.WEEKLY_REST_REGULAR - short,
                   comp.WEEKLY_REST_REGULAR - 9 * 60,
                   comp.WEEKLY_REST_REGULAR - 18 * 60),
            taken, taken + timedelta(minutes=debt["rest_minutes"]),
            breach["detail"], comp.WEEKLY_REST_REGULAR, debt["rest_minutes"]))
    return out


ALL_RULES = [
    check_continuous_driving,
    check_daily_driving,
    check_daily_rest,
    check_weekly_rest,
    check_weekly_compensation,
    check_weekly_driving,
    check_wtd,
]


def analyse(activities: list[Activity],
            places: list[PlaceEntry] | None = None,
            card_gaps: list[CardGap] | None = None,
            unverified_crew: bool = False) -> list[Infringement]:
    """Run every rule over one driver's timeline, newest first.

    `places` and `card_gaps` come from the same card as the activities. They are
    optional: without them the record-keeping rules simply do not run, rather
    than reporting every day as missing its country entry.

    `unverified_crew` says the reader could not tell which card slot was used -
    so a rest that is short for one driver but legal for a crew is raised as
    something to confirm rather than as an infringement.
    """
    acts = _prepare(activities)
    days = _duty_days(acts)
    found: list[Infringement] = []
    found += check_continuous_driving(acts)
    found += check_daily_driving(days)
    found += check_daily_rest(days, unverified_crew)
    found += check_weekly_rest(days)
    found += check_weekly_driving(acts)
    found += check_wtd(days)
    if places is not None:
        found += check_country_entries(days, places)
        if card_gaps:
            found += check_card_withdrawal(days, card_gaps, places)
    found.sort(key=lambda i: i.start, reverse=True)
    return found

"""The whole depot's week on one screen.

A transport office does not start the day wondering about one driver; it starts
by asking who has not handed their card in, and who has picked something up
that needs a conversation. That question is badly served by a report you run
one driver at a time, which is what we had.

So this is a grid: a row per driver, a cell per day. A cell says what the card
shows for that day - worked, rested, or nothing at all - and whether anything
was found. The important cell is the empty one: a day with no record is either
a card that has not been downloaded or a driver who was not there, and the
office needs to know which.

Everything here is worked out from data already held. It adds no analysis; it
only puts what we know where somebody can see it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.services import wtd

# What a day's cell can say.
WORKED, RESTED, NOTHING = "worked", "rested", "no_data"

# Working time a driver may still put in, judged against both limits that bite:
# 60 hours in any single week, and a 48-hour average across the reference
# period. Whichever is tighter is the one that matters.
WEEK_LIMIT = wtd.WEEK_LIMIT
AVERAGE_LIMIT = wtd.AVERAGE_LIMIT


def week_start(day: date) -> date:
    return wtd.week_start(day)


def span(end: date, weeks: int) -> tuple[date, date]:
    """The whole weeks to show, ending with the week `end` falls in.

    Calendars are read in whole weeks - a grid that starts on a Wednesday is
    unreadable - so the range always runs Monday to Sunday.
    """
    last = week_start(end) + timedelta(days=6)
    first = week_start(end) - timedelta(weeks=weeks - 1)
    return first, last


def _shift(first: datetime | None, last: datetime | None) -> int | None:
    """How long the driver was on duty, first working minute to last."""
    if first is None or last is None:
        return None
    return max(0, int((last - first).total_seconds() // 60))


def _cells(days: dict, infringements: dict[date, list], first: date, last: date) -> list[dict]:
    out = []
    cursor = first
    while cursor <= last:
        day = days.get(cursor)
        found = infringements.get(cursor, [])
        if day is None:
            state = NOTHING
        elif day["drive"] or day["work"]:
            state = WORKED
        else:
            state = RESTED
        cell = {
            "date": cursor.isoformat(),
            "state": state,
            "drive": day["drive"] if day else 0,
            "work": day["work"] if day else 0,
            "poa": day["available"] if day else 0,
            "rest": day["rest"] if day else 0,
            "working": (day["drive"] + day["work"]) if day else 0,
            "shift": _shift(day["first"], day["last"]) if day else None,
            "start": day["first"].strftime("%H:%M") if day and day["first"] else None,
            "end": day["last"].strftime("%H:%M") if day and day["last"] else None,
            "night": bool(day["night"]) if day else False,
            "infringements": len(found),
            "worst": _worst(found),
        }
        out.append(cell)
        cursor += timedelta(days=1)
    return out


SEVERITY_ORDER = {"very_serious": 0, "serious": 1, "minor": 2}


def _worst(found: list[str]) -> str | None:
    if not found:
        return None
    return sorted(found, key=lambda s: SEVERITY_ORDER.get(s, 9))[0]


def _weekly_totals(cells: list[dict]) -> list[dict]:
    """A total per week, so a row reads across as well as down."""
    weeks: dict[str, dict] = {}
    for cell in cells:
        day = date.fromisoformat(cell["date"])
        key = week_start(day).isoformat()
        week = weeks.setdefault(key, {"week_start": key, "drive": 0, "work": 0, "poa": 0,
                                      "working": 0, "days": 0, "infringements": 0})
        week["drive"] += cell["drive"]
        week["work"] += cell["work"]
        week["poa"] += cell["poa"]
        week["working"] += cell["working"]
        week["infringements"] += cell["infringements"]
        if cell["state"] == WORKED:
            week["days"] += 1
    return [weeks[k] for k in sorted(weeks)]


def headroom(days: dict, today: date, reference_weeks: int = 17) -> dict:
    """How much more the driver may work this week and next.

    Two different limits apply, and they are deliberately reported separately
    rather than collapsed into one figure:

    `available_this_week` is the hard one - 60 hours in any single week. It is
    never wrong and never needs explaining.

    `average_headroom` is how much may be worked this week while keeping the
    rolling average at or below 48 hours. It can be negative, which is the
    useful case: it means the driver is already running hot and needs a lighter
    week, and a planner has no way of working that out in their head.

    Collapsing the two would misreport both ends. A driver in their first week
    may legitimately work 60 hours - the average is judged across the reference
    period, not at every point inside it - so the average is only reported once
    there is an earlier week to average against. Equally, a driver well over
    the average must not be told they have the full 60 hours available.

    Weeks with no working time are left out of the average, matching the
    regulations and the WTD report, so a fortnight's leave does not silently
    buy a driver extra hours.
    """
    this_week = week_start(today)
    per_week: dict[date, int] = {}
    for day, totals in days.items():
        working = totals["drive"] + totals["work"]
        if working:
            per_week[week_start(day)] = per_week.get(week_start(day), 0) + working

    worked_this_week = per_week.get(this_week, 0)
    available = max(0, WEEK_LIMIT - worked_this_week)

    def earlier(upto: date) -> list[int]:
        return [v for k, v in per_week.items()
                if upto - timedelta(weeks=reference_weeks) < k < upto]

    # This week, against the average. Only meaningful once there is an earlier
    # week to average with - a single week is not an average of anything.
    others = earlier(this_week)
    average_headroom = (AVERAGE_LIMIT * (len(others) + 1) - sum(others) - worked_this_week
                        if others else None)

    # Next week, assuming this week finishes exactly where it stands now. A
    # planning figure, not a promise: more work this week lowers it.
    later = earlier(this_week + timedelta(weeks=1))
    allowed_next = (AVERAGE_LIMIT * (len(later) + 1) - sum(later)) if later else WEEK_LIMIT
    available_next = max(0, min(WEEK_LIMIT, allowed_next))

    window = [per_week[this_week - timedelta(weeks=i)]
              for i in range(reference_weeks)
              if (this_week - timedelta(weeks=i)) in per_week]
    binding = (average_headroom is not None and average_headroom < available)
    return {
        "worked_this_week": worked_this_week,
        "available_this_week": available,
        "average_headroom": average_headroom,
        "over_average": average_headroom is not None and average_headroom < 0,
        "available_next_week": available_next,
        "average": round(sum(window) / len(window)) if window else None,
        "weeks_in_average": len(window),
        "limited_by": (f"the {reference_weeks}-week average" if binding
                       else "the 60-hour week"),
    }


def build(driver_ref: str, name: str | None, spans, found: dict[date, list],
          first: date, last: date, today: date, last_download: datetime | None = None,
          reference_weeks: int = 17) -> dict:
    """One driver's row: a cell per day, the weekly totals, and where they stand."""
    days = wtd.daily(spans) if spans else {}
    cells = _cells(days, found, first, last)
    missing = [c["date"] for c in cells
               if c["state"] == NOTHING and date.fromisoformat(c["date"]) <= today]
    return {
        "driver_ref": driver_ref,
        "name": name or driver_ref,
        "cells": cells,
        "weeks": _weekly_totals(cells),
        "worked_days": sum(1 for c in cells if c["state"] == WORKED),
        "infringements": sum(c["infringements"] for c in cells),
        # Days inside the range, up to today, with nothing on the card at all.
        # This is the number the office acts on.
        "days_without_a_record": len(missing),
        "missing_dates": missing,
        "last_download": last_download.date().isoformat() if last_download else None,
        "days_since_download": ((today - last_download.date()).days
                                if last_download else None),
        **headroom(days, today, reference_weeks),
    }

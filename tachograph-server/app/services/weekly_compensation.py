"""Reduced weekly rest, and the debt it leaves behind.

A driver may cut a weekly rest from 45 hours to as little as 24, but the hours
they skipped are owed back. The repayment has conditions that make this
awkward to check by eye, which is exactly why it gets missed:

  * the debt is the shortfall: 45 hours less whatever was actually taken;
  * it must be repaid by the end of the third week following the one it was
    taken in - so a reduction in week N is due by the end of week N+3;
  * the repayment has to be one unbroken block of at least the debt, attached
    to another rest period of at least 9 hours. Repaying it in dribs and drabs
    across several days does not count.

The important behaviour is what this does *not* do. A debt inside its window
is not an infringement - it is a perfectly normal thing for a driver to be
carrying, and flagging it would train an operator to ignore the warning. Only
a debt still outstanding when week N+3 closes is a breach, and only then is
anything raised.

That also means a debt raised near the end of the data is left alone: the
weeks it could still be repaid in have not been downloaded yet, and calling
that an infringement would be an accusation the data cannot support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta  # noqa: F401  (date used in annotations)

WEEKLY_REST_REGULAR = 45 * 60
WEEKLY_REST_REDUCED = 24 * 60
# The repayment must be attached to a rest of at least this long - in practice
# a daily or weekly rest, not a gap between two shifts.
ATTACHED_REST_MIN = 9 * 60
# Weeks after the reduction in which the debt may still be cleared.
REPAY_WITHIN_WEEKS = 3


def week_of(when: datetime | date) -> date:
    """The Monday of the fixed week a moment falls in."""
    day = when.date() if isinstance(when, datetime) else when
    return day - timedelta(days=day.weekday())


@dataclass
class Debt:
    """One reduced weekly rest, and whether it was ever paid back."""
    taken_at: datetime
    rest_minutes: int
    week: date
    deficit: int
    due_by: date                       # the last day of week N+3
    repaid_at: datetime | None = None
    repaid_minutes: int | None = None

    @property
    def open(self) -> bool:
        return self.repaid_at is None

    def as_dict(self) -> dict:
        return {
            "taken_at": self.taken_at.isoformat(),
            "rest_minutes": self.rest_minutes,
            "week": self.week.isoformat(),
            "deficit_minutes": self.deficit,
            "due_by": self.due_by.isoformat(),
            "repaid_at": self.repaid_at.isoformat() if self.repaid_at else None,
            "repaid_minutes": self.repaid_minutes,
            "open": self.open,
        }


@dataclass
class Rest:
    """A rest period the timeline actually contains.

    Spans are merged before they reach here, so a compensating block taken
    together with another rest arrives as one continuous rest rather than two
    touching ones - which is what "en bloc, attached to" describes.
    """
    start: datetime
    end: datetime
    minutes: int


@dataclass
class Ledger:
    """Every reduced weekly rest a driver has taken, and its repayment."""
    debts: list[Debt] = field(default_factory=list)

    def open_debts(self, on: date | None = None) -> list[Debt]:
        return [d for d in self.debts
                if d.open and (on is None or d.week <= on)]

    def total_open(self) -> int:
        return sum(d.deficit for d in self.debts if d.open)


def _due_by(week: date) -> date:
    """The last day of the third week following the reduction."""
    return week + timedelta(weeks=REPAY_WITHIN_WEEKS, days=6)


def build(rests: list[Rest], *, data_ends: date | None = None) -> tuple[Ledger, list[dict]]:
    """Work through the driver's weekly rests in order.

    Returns the ledger and the breaches: a breach is a debt whose repayment
    window closed with nothing to clear it, and which the data actually covers
    long enough to say so.
    """
    ledger = Ledger()
    breaches: list[dict] = []
    ordered = sorted(rests, key=lambda r: r.start)

    # Which rest is a week's *weekly* rest matters, because only that one can
    # be short and create a debt. The longest rest of at least 24 hours in the
    # fixed week is taken as it, which is how an analyser reads a card: a
    # driver who rests 30 hours mid-week and 45 at the weekend has taken a full
    # weekly rest, and the 30 is available to pay off an older debt.
    weekly: dict[date, Rest] = {}
    for rest in ordered:
        if rest.minutes < WEEKLY_REST_REDUCED:
            continue
        week = week_of(rest.start)
        if week not in weekly or rest.minutes > weekly[week].minutes:
            weekly[week] = rest

    for rest in ordered:
        week = week_of(rest.start)
        is_weekly = weekly.get(week) is rest

        # What this block must be worth to clear a debt: the shortfall itself,
        # plus the rest it has to be attached to. Attached to an ordinary rest
        # that is 9 hours; where the block doubles as the week's own weekly
        # rest it has to cover a full 45 as well, or it is simply another
        # reduced week.
        attached = WEEKLY_REST_REGULAR if is_weekly else ATTACHED_REST_MIN

        # Oldest debt first, so the one closest to its deadline is settled
        # before a newer one.
        for debt in sorted((d for d in ledger.debts if d.open), key=lambda d: d.due_by):
            if debt.week >= week:
                continue              # cannot repay a reduction not yet taken
            if week > week_of(debt.due_by):
                continue              # too late for this one
            if rest.minutes >= debt.deficit + attached:
                debt.repaid_at = rest.start
                debt.repaid_minutes = rest.minutes
                break                 # one block settles one debt

        # Only the week's own weekly rest can be short and leave a debt.
        if is_weekly and rest.minutes < WEEKLY_REST_REGULAR:
            ledger.debts.append(Debt(
                taken_at=rest.start, rest_minutes=rest.minutes, week=week,
                deficit=WEEKLY_REST_REGULAR - rest.minutes, due_by=_due_by(week)))

    # Only judge debts whose window has actually closed inside the data. A
    # debt taken last week has three weeks to run and is not a breach.
    for debt in ledger.debts:
        if not debt.open:
            continue
        if data_ends is not None and data_ends <= debt.due_by:
            continue                  # still in time, or the data stops first
        breaches.append({
            "debt": debt.as_dict(),
            "detail": (
                f"the weekly rest of {_hm(debt.rest_minutes)} taken on "
                f"{debt.taken_at:%d/%m/%Y} was {_hm(debt.deficit)} short of the "
                f"{_hm(WEEKLY_REST_REGULAR)} regular weekly rest. That "
                f"{_hm(debt.deficit)} had to be paid back in one unbroken block, "
                f"attached to a rest of at least {_hm(ATTACHED_REST_MIN)}, by the "
                f"end of {debt.due_by:%d/%m/%Y}. It was not."),
        })
    return ledger, breaches


def _hm(minutes: int) -> str:
    return f"{minutes // 60}h{minutes % 60:02d}"


def rests_from_days(days) -> list[Rest]:
    """The rest periods in a driver's timeline, longest-first within a moment.

    Every duty day carries the rest that closed it; taking those gives each
    rest exactly once, in order.
    """
    out: list[Rest] = []
    for day in days:
        if not (day.closed_by_rest and day.rest_after and day.rest_start and day.rest_end):
            continue
        out.append(Rest(start=day.rest_start, end=day.rest_end, minutes=day.rest_after))
    return out

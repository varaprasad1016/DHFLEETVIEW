"""Working out what a customer owes for a month.

Customers are billed monthly for the vehicles on their account, and a vehicle
is charged only for the days it was actually there. Two rules follow from that:

  * a customer who joins on the 18th pays for the 18th to the end of that
    month, and whole months after it;
  * a vehicle fitted on the 18th is charged the same way, in any month.

Both are the same calculation - days present over days in the month - so there
is one of it here rather than a special case for new accounts.

What a vehicle costs depends on what is fitted to it. A vehicle with a camera,
a tracker and a tachograph is three charges, each shown on its own line, so a
customer querying an invoice can see exactly what they are paying for rather
than one unexplained figure.

Money is Decimal throughout and rounded once, at the line. Floats do not
survive contact with an accounts department.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

PENNY = Decimal("0.01")

# What a vehicle is charged for, and the order it reads on an invoice.
#
# A vehicle is on one package, not a list of parts. Adding the parts up would
# say a vehicle with a camera and a tachograph costs the two added together,
# which is not what is charged: the tachograph package already includes the
# live view, at a price agreed for the pair.
PACKAGES = ("live", "tacho")

# What each package is called where a person reads it.
PACKAGE_NAMES = {"live": "Live view",
                 "tacho": "Tacho tracking + live view"}


def package_for(fitted) -> str:
    """Which package a vehicle is on, from what is fitted to it.

    Tachograph work is the thing that moves a vehicle up: a vehicle whose cards
    and unit downloads are being processed is on the higher package, and
    everything else - a camera, a tracker, or both - is on the lower one.
    """
    return "tacho" if "tachograph" in (fitted or ()) else "live"


def month_range(year: int, month: int) -> tuple[date, date]:
    """The first and last day of a month, both included."""
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def months_of(year: int, month: int, count: int) -> list[tuple[int, int]]:
    """`count` months ending with the given one, earliest first.

    A quarter ending in September is July, August, September - the months a
    quarterly invoice is made of.
    """
    out = []
    for step in range(count - 1, -1, -1):
        index = (year * 12 + month - 1) - step
        out.append((index // 12, index % 12 + 1))
    return out


def period_range(year: int, month: int, count: int) -> tuple[date, date]:
    """The whole span those months cover, both ends included."""
    months = months_of(year, month, count)
    return month_range(*months[0])[0], month_range(*months[-1])[1]


def period_key(year: int, month: int, count: int) -> str:
    """How a billing period is named where it has to be recognised again.

    Quarters read as quarters ("2026-Q3") because that is what an accountant
    calls them; anything else is named by the month it ends in.
    """
    if count == 3 and month % 3 == 0:
        return f"{year}-Q{month // 3}"
    if count == 1:
        return f"{year}-{month:02d}"
    return f"{year}-{month:02d}x{count}"


def last_closed_period(today: date, count: int) -> tuple[int, int]:
    """The month the most recently completed billing period ended in.

    This is what makes a missed run recoverable. A server that was off on the
    1st of October still knows, when it comes up on the 3rd, that the quarter
    ending in September has closed and has not been invoiced - rather than
    having to have been running at the moment the calendar turned over.
    """
    index = today.year * 12 + today.month - 2        # the month before this one
    if count > 1 and 12 % count == 0:
        while (index % 12 + 1) % count:
            index -= 1
    return index // 12, index % 12 + 1


def period_closing(day: date, count: int) -> tuple[int, int] | None:
    """The period that ended yesterday, if `day` is the morning it closes on.

    Periods are anchored to the calendar year rather than to whenever the
    server was last started, so a three-month cycle always closes on 1 January,
    1 April, 1 July and 1 October - and a restart cannot shift it.
    """
    if day.day != 1 or count < 1:
        return None
    ended = date(day.year, day.month, 1) - timedelta(days=1)
    if (12 % count == 0) and ended.month % count:
        return None            # not the last month of a period
    return ended.year, ended.month


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def chargeable_days(period_start: date, period_end: date, present_from: date | None) -> int:
    """How many days of this period the thing was actually there for.

    Counted inclusively: a vehicle present on the 18th of a 30-day month is
    charged 13 days, the 18th itself included. Something that arrived after the
    period ended is charged nothing.
    """
    start = period_start if present_from is None else max(period_start, present_from)
    if start > period_end:
        return 0
    return (period_end - start).days + 1


@dataclass
class Line:
    """One charge on an invoice."""
    vehicle: str
    item: str                 # the package: live / tacho
    rate: Decimal             # the full monthly rate
    days: int
    days_in_month: int
    amount: Decimal = Decimal("0.00")

    @property
    def part_month(self) -> bool:
        return self.days < self.days_in_month

    def describe(self) -> str:
        """What this line says on the paper."""
        item = PACKAGE_NAMES.get(self.item, self.item.title())
        if self.part_month:
            return f"{self.vehicle} — {item} ({self.days} of {self.days_in_month} days)"
        return f"{self.vehicle} — {item}"


@dataclass
class Invoice:
    """What a customer owes for one month, before it is given a number."""
    account: str
    period_start: date
    period_end: date
    lines: list[Line] = field(default_factory=list)
    vat_rate: Decimal = Decimal("0.20")

    @property
    def net(self) -> Decimal:
        return sum((line.amount for line in self.lines), Decimal("0.00"))

    @property
    def vat(self) -> Decimal:
        return (self.net * self.vat_rate).quantize(PENNY, rounding=ROUND_HALF_UP)

    @property
    def total(self) -> Decimal:
        return self.net + self.vat

    @property
    def period(self) -> str:
        """How the period reads on the invoice."""
        whole_month = (self.period_start.day == 1
                       and (self.period_start.year, self.period_start.month)
                       == (self.period_end.year, self.period_end.month))
        if whole_month:
            return self.period_start.strftime("%B %Y")
        # Anything else - a quarter, or a part month - says so plainly, since
        # the customer will check it against the dates they expect.
        start = f"{self.period_start.day} {self.period_start.strftime('%B')}"
        if self.period_start.year != self.period_end.year:
            start += f" {self.period_start.year}"
        end = f"{self.period_end.day} {self.period_end.strftime('%B %Y')}"
        return f"{start} to {end}"


def price_vehicle(vehicle: dict, rates: dict[str, Decimal], period_start: date,
                  period_end: date) -> list[Line]:
    """The charge for one vehicle over one period.

    `vehicle` says what it is and when it arrived:
        {"name": "PJ19FBK", "since": date(2026, 9, 18),
         "fitted": ["tracking", "camera"]}
    A vehicle that arrived before this period is simply charged the whole of it.

    One vehicle is one charge, for the package it is on. A list is still
    returned because a vehicle that arrived after the period ended, or is on a
    package with no agreed rate, is charged nothing at all.
    """
    total_days = days_in_month(period_start.year, period_start.month)
    days = chargeable_days(period_start, period_end, vehicle.get("since"))
    if days <= 0:
        return []

    item = package_for(vehicle.get("fitted"))
    rate = rates.get(item)
    if not rate:
        return []           # nothing charged for a package with no agreed rate

    line = Line(vehicle=vehicle["name"], item=item, rate=Decimal(rate),
                days=days, days_in_month=total_days)
    line.amount = (Decimal(rate) * Decimal(days) / Decimal(total_days)).quantize(
        PENNY, rounding=ROUND_HALF_UP)
    return [line]


def build_invoice(account: str, vehicles: list[dict], rates: dict[str, Decimal],
                  year: int, month: int, account_since: date | None = None,
                  vat_rate: Decimal = Decimal("0.20")) -> Invoice:
    """Everything a customer owes for one month.

    `account_since` shortens the very first period: an account opened on the
    18th is billed from the 18th, and nothing before it is charged for.
    """
    period_start, period_end = month_range(year, month)
    if account_since and period_start <= account_since <= period_end:
        period_start = account_since
    if account_since and account_since > period_end:
        return Invoice(account, period_start, period_end, [], vat_rate)

    invoice = Invoice(account=account, period_start=period_start,
                      period_end=period_end, vat_rate=vat_rate)
    for vehicle in sorted(vehicles, key=lambda v: v["name"]):
        invoice.lines.extend(price_vehicle(vehicle, rates, period_start, period_end))
    return invoice


def build_period(account: str, vehicles: list[dict], rates: dict[str, Decimal],
                 year: int, month: int, months: int = 1,
                 account_since: date | None = None,
                 vat_rate: Decimal = Decimal("0.20")) -> Invoice:
    """One invoice covering several months, ending with the month given.

    A quarter is not priced as a three-month block: each month is worked out on
    its own and the charges added together. That is the only way the sums stay
    right across months of different lengths and vehicles that arrive part way
    through - a vehicle fitted on 18 August is charged 14 of August's 31 days
    and the whole of September, which a single span could not express.
    """
    if months <= 1:
        return build_invoice(account, vehicles, rates, year, month,
                             account_since, vat_rate)

    spans = months_of(year, month, months)
    lines: list[Line] = []
    first_charged: date | None = None
    for span_year, span_month in spans:
        part = build_invoice(account, vehicles, rates, span_year, span_month,
                             account_since, vat_rate)
        if part.lines and first_charged is None:
            first_charged = part.period_start
        lines.extend(part.lines)

    start, end = period_range(year, month, months)
    # An account that joined mid-period is billed from the day it joined, not
    # from the start of a quarter it was not a customer for.
    if account_since and start < account_since <= end:
        start = account_since
    return Invoice(account=account, period_start=first_charged or start,
                   period_end=end, lines=lines, vat_rate=vat_rate)

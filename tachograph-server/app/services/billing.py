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
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

PENNY = Decimal("0.01")

# What can be fitted to a vehicle, and the order it reads on an invoice.
CHARGEABLE = ("tracking", "camera", "tachograph")


def month_range(year: int, month: int) -> tuple[date, date]:
    """The first and last day of a month, both included."""
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


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
    item: str                 # tracking / camera / tachograph
    rate: Decimal             # the full monthly rate
    days: int
    days_in_month: int
    amount: Decimal = Decimal("0.00")

    @property
    def part_month(self) -> bool:
        return self.days < self.days_in_month

    def describe(self) -> str:
        """What this line says on the paper."""
        names = {"tracking": "Vehicle tracking", "camera": "Camera system",
                 "tachograph": "Tachograph compliance"}
        item = names.get(self.item, self.item.title())
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
        if self.period_start.day == 1:
            return self.period_start.strftime("%B %Y")
        # A part month says so plainly, since the customer will check it.
        start = f"{self.period_start.day} {self.period_start.strftime('%B')}"
        end = f"{self.period_end.day} {self.period_end.strftime('%B %Y')}"
        return f"{start} to {end}"


def price_vehicle(vehicle: dict, rates: dict[str, Decimal], period_start: date,
                  period_end: date) -> list[Line]:
    """The charges for one vehicle over one period.

    `vehicle` says what it is and when it arrived:
        {"name": "PJ19FBK", "since": date(2026, 9, 18),
         "fitted": ["tracking", "camera"]}
    A vehicle that arrived before this period is simply charged the whole of it.
    """
    total_days = days_in_month(period_start.year, period_start.month)
    days = chargeable_days(period_start, period_end, vehicle.get("since"))
    if days <= 0:
        return []

    lines: list[Line] = []
    for item in CHARGEABLE:
        if item not in vehicle.get("fitted", ()):
            continue
        rate = rates.get(item)
        if not rate:
            continue        # nothing charged for something with no agreed rate
        line = Line(vehicle=vehicle["name"], item=item, rate=Decimal(rate),
                    days=days, days_in_month=total_days)
        line.amount = (Decimal(rate) * Decimal(days) / Decimal(total_days)).quantize(
            PENNY, rounding=ROUND_HALF_UP)
        lines.append(line)
    return lines


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

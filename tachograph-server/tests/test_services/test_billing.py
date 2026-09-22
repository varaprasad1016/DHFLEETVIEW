"""What a customer is charged for a month.

The rules being checked: a customer joining mid-month pays from the day they
joined, a vehicle fitted mid-month is charged the same way, and a customer who
has been there all along pays for a whole month. Rounding is checked because a
penny out on every line is what an accounts department notices first.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.billing import (build_invoice, chargeable_days, days_in_month,
                                  month_range, price_vehicle)

RATES = {"tracking": Decimal("12.00"), "camera": Decimal("30.00"),
         "tachograph": Decimal("6.00")}


def vehicle(name, since=None, fitted=("tracking",)):
    return {"name": name, "since": since, "fitted": list(fitted)}


def test_a_full_month_is_charged_in_full():
    invoice = build_invoice("Darnoa Haulage", [vehicle("PJ19FBK", date(2026, 1, 5))],
                            RATES, 2026, 9)
    assert invoice.period == "September 2026"
    assert invoice.net == Decimal("12.00")
    assert invoice.lines[0].part_month is False


def test_a_customer_joining_on_the_18th_pays_from_the_18th():
    """18 September to 30 September is 13 days of a 30-day month."""
    invoice = build_invoice("Darnoa Haulage", [vehicle("PJ19FBK", date(2026, 9, 18))],
                            RATES, 2026, 9, account_since=date(2026, 9, 18))
    assert invoice.period == "18 September to 30 September 2026"
    assert invoice.lines[0].days == 13
    assert invoice.net == Decimal("5.20")          # 12.00 * 13/30
    assert invoice.total == Decimal("6.24")        # plus 20% VAT


def test_the_month_after_joining_is_a_whole_month():
    invoice = build_invoice("Darnoa Haulage", [vehicle("PJ19FBK", date(2026, 9, 18))],
                            RATES, 2026, 10, account_since=date(2026, 9, 18))
    assert invoice.period == "October 2026"
    assert invoice.lines[0].days == 31
    assert invoice.net == Decimal("12.00")


def test_a_vehicle_fitted_mid_month_is_charged_from_that_day():
    """The same rule as a new account, applied to one vehicle on an old one."""
    invoice = build_invoice("Darnoa Haulage",
                            [vehicle("NX71SCV", date(2025, 1, 1)),
                             vehicle("PJ19FBK", date(2026, 9, 18))],
                            RATES, 2026, 9)
    charged = {line.vehicle: line.days for line in invoice.lines}
    assert charged == {"NX71SCV": 30, "PJ19FBK": 13}


def test_a_vehicle_added_after_the_month_is_not_charged_at_all():
    invoice = build_invoice("Darnoa Haulage", [vehicle("PJ19FBK", date(2026, 10, 3))],
                            RATES, 2026, 9)
    assert invoice.lines == []
    assert invoice.net == Decimal("0.00")


def test_each_thing_fitted_is_its_own_line():
    """A customer querying an invoice must be able to see what they pay for."""
    invoice = build_invoice("Darnoa Haulage",
                            [vehicle("PJ19FBK", date(2026, 1, 1),
                                     fitted=("tracking", "camera", "tachograph"))],
                            RATES, 2026, 9)
    assert [line.item for line in invoice.lines] == ["tracking", "camera", "tachograph"]
    assert invoice.net == Decimal("48.00")


def test_something_fitted_with_no_agreed_rate_is_not_charged():
    invoice = build_invoice("Darnoa Haulage",
                            [vehicle("PJ19FBK", date(2026, 1, 1), fitted=("tracking", "camera"))],
                            {"tracking": Decimal("12.00")}, 2026, 9)
    assert [line.item for line in invoice.lines] == ["tracking"]


def test_vat_is_added_on_the_whole_invoice_not_each_line():
    """Rounding per line then summing VAT drifts; this must not."""
    vehicles = [vehicle(f"V{n}", date(2026, 1, 1)) for n in range(3)]
    invoice = build_invoice("Darnoa Haulage", vehicles, {"tracking": Decimal("0.99")}, 2026, 9)
    assert invoice.net == Decimal("2.97")
    assert invoice.vat == Decimal("0.59")          # 0.594 rounded half up
    assert invoice.total == Decimal("3.56")


def test_part_months_round_to_the_penny():
    """13/30 of 30.00 is 13.00; 13/31 of 30.00 is 12.5806... and must round."""
    september = price_vehicle(vehicle("V", date(2026, 9, 18), ("camera",)),
                              RATES, date(2026, 9, 1), date(2026, 9, 30))
    october = price_vehicle(vehicle("V", date(2026, 10, 19), ("camera",)),
                            RATES, date(2026, 10, 1), date(2026, 10, 31))
    assert september[0].amount == Decimal("13.00")
    assert october[0].amount == Decimal("12.58")


def test_february_is_short_and_leap_years_are_longer():
    assert days_in_month(2026, 2) == 28
    assert days_in_month(2028, 2) == 29
    invoice = build_invoice("Darnoa Haulage", [vehicle("V", date(2028, 2, 15))],
                            RATES, 2028, 2, account_since=date(2028, 2, 15))
    assert invoice.lines[0].days == 15             # 15th to 29th inclusive
    assert invoice.net == Decimal("6.21")          # 12.00 * 15/29


def test_the_day_a_vehicle_arrives_is_charged():
    """Inclusive counting: arriving on the last day of the month costs one day."""
    assert chargeable_days(date(2026, 9, 1), date(2026, 9, 30), date(2026, 9, 30)) == 1
    assert chargeable_days(date(2026, 9, 1), date(2026, 9, 30), None) == 30


def test_a_part_month_line_says_so_on_the_invoice():
    invoice = build_invoice("Darnoa Haulage", [vehicle("PJ19FBK", date(2026, 9, 18))],
                            RATES, 2026, 9, account_since=date(2026, 9, 18))
    assert invoice.lines[0].describe() == "PJ19FBK — Vehicle tracking (13 of 30 days)"


def test_a_whole_month_line_does_not_mention_days():
    invoice = build_invoice("Darnoa Haulage", [vehicle("PJ19FBK", date(2026, 1, 1))],
                            RATES, 2026, 9)
    assert invoice.lines[0].describe() == "PJ19FBK — Vehicle tracking"


def test_month_range_covers_the_whole_month():
    assert month_range(2026, 9) == (date(2026, 9, 1), date(2026, 9, 30))

"""The fleet-level tachograph reports.

What is being checked is the part that would be wrong silently: which band a
download falls in, that a vehicle nobody has ever downloaded is red rather than
blank, how an infringement becomes points and a level, and that a week with no
work stays out of the working-time average instead of being counted as zero.

The database-backed halves of these reports are not exercised here - they are
thin queries over the archive - but every judgement they hand off to is.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.services import wtd
from app.services.performance import (DEFAULT_LEVELS, DISPUTED, NO_FAULT,
                                      Scheme, _state)
from app.services.submission import CARD_BANDS, VU_BANDS, _band, _name_key
from app.services.tacho_pdf import COLUMNS, FORTNIGHT_COLUMN


# ------------------------------------------------------------------ banding

def test_a_unit_downloaded_today_is_green():
    assert _band(0, VU_BANDS) == "green"
    assert _band(14, VU_BANDS) == "green"


def test_a_unit_is_amber_from_fifteen_days_and_red_from_fiftyseven():
    assert _band(15, VU_BANDS) == "amber"
    assert _band(56, VU_BANDS) == "amber"
    assert _band(57, VU_BANDS) == "red"


def test_a_card_turns_red_a_day_after_the_twentyeight_day_limit():
    assert _band(28, CARD_BANDS) == "amber"
    assert _band(29, CARD_BANDS) == "red"


def test_never_downloaded_is_red_not_unknown():
    # The row this report exists to surface. A blank here reads as "nothing to
    # worry about", which is the opposite of what it means.
    assert _band(None, VU_BANDS) == "red"
    assert _band(None, CARD_BANDS) == "red"


def test_driver_names_compare_in_full():
    # card_key truncates to 14 characters, which is right for a card number and
    # wrong for a name: these two must not collapse onto each other.
    assert _name_key("CHRISTOPHERSON ALAN") != _name_key("CHRISTOPHERSON ALEX")
    assert _name_key("ROHAN NARANG -") == _name_key("rohan  narang")


# ------------------------------------------------------- performance scheme

class _Review:
    def __init__(self, action=None, signed=None):
        self.debrief_action = action
        self.driver_signed_at = signed


def test_an_item_nobody_has_debriefed_is_open():
    assert _state(None) == "open"
    assert _state(_Review()) == "open"


def test_a_debriefed_item_is_outstanding_until_the_driver_signs():
    assert _state(_Review("verbal_warning")) == "accepted"
    assert _state(_Review("verbal_warning", signed=datetime.now(timezone.utc))) == "closed"


def test_a_disputed_item_stays_disputed_even_once_signed():
    assert _state(_Review(DISPUTED)) == "disputed"
    assert _state(_Review(DISPUTED, signed=datetime.now(timezone.utc))) == "disputed"


def test_severity_scores_follow_the_annex_grading():
    s = Scheme()
    assert s.score("minor") < s.score("serious") < s.score("very_serious")
    # An unrecognised grade scores nothing rather than guessing a middle value.
    assert s.score("unheard_of") == 0


def test_levels_are_banded_and_open_ended_at_the_top():
    s = Scheme()
    assert s.level(0) == 0
    assert s.level(1) == 1
    assert s.level(DEFAULT_LEVELS[-1][1]) == 5
    assert s.level(DEFAULT_LEVELS[-1][1] + 500) == 5


def test_each_band_is_reachable():
    # A band no score can land in is a scheme that silently never promotes.
    s = Scheme()
    for level, threshold in DEFAULT_LEVELS:
        assert s.level(threshold) == level


# ------------------------------------------------------- working time grid

def _span(kind, day, hours, at=8):
    start = datetime.combine(day, datetime.min.time(), timezone.utc).replace(hour=at)
    return (kind, start, start + timedelta(hours=hours))


def test_a_week_with_no_work_is_blank_and_left_out_of_the_average():
    monday = date(2026, 10, 5)
    # Two weeks worked, the week between them not worked at all.
    spans = [_span("drive", monday, 5), _span("drive", monday + timedelta(days=14), 9)]
    grid = wtd.reference_grid({"TEST DRIVER": spans}, reference_weeks=3,
                              today=monday + timedelta(days=14))
    driver = grid["drivers"][0]

    assert driver["cells"] == [5 * 60, None, 9 * 60]
    assert driver["weeks_worked"] == 2
    # 7 hours, not the 4h40m that counting the blank week as zero would give.
    assert driver["average_minutes"] == 7 * 60


def test_a_week_over_sixty_hours_is_counted():
    monday = date(2026, 10, 5)
    spans = [_span("drive", monday + timedelta(days=n), 9) for n in range(7)]
    grid = wtd.reference_grid({"TEST DRIVER": spans}, reference_weeks=1, today=monday)
    assert grid["drivers"][0]["weeks_over_60"] == 1


def test_availability_is_not_working_time():
    monday = date(2026, 10, 5)
    grid = wtd.reference_grid(
        {"TEST DRIVER": [_span("drive", monday, 4), _span("available", monday, 4, at=14)]},
        reference_weeks=1, today=monday)
    assert grid["drivers"][0]["cells"] == [4 * 60]


# --------------------------------------------------------- the column bug

def test_the_fortnight_total_sits_under_its_own_heading():
    # It was written to index 15 - "WTD active" - so a rest day printed the
    # fortnight's driving as though the driver had worked it that day.
    assert COLUMNS[FORTNIGHT_COLUMN][0].startswith("Fort")
    assert "WTD" in COLUMNS[15][0]

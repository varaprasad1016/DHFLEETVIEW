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


# ----------------------------------------------------- missing VU mileage

from app.services.vu_mileage import _band as mm_band, _dedupe, _merge, gaps_for
from datetime import datetime, timezone


def _sess(odo_in, odo_out, slot=0, mins=0):
    # `mins` orders sessions in time, which is how the real ones are ordered.
    t = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(minutes=mins)
    return {"slot": slot, "ref": "X", "inserted": t, "withdrawn": t,
            "odo_in": odo_in, "odo_out": odo_out}


def test_a_gap_between_two_card_sessions_is_missing_mileage():
    # Withdraw at 1000, next insertion at 1040 → 40 km driven on no card.
    gaps = gaps_for([_sess(900, 1000, mins=0), _sess(1040, 1100, mins=60)], threshold_km=3)
    assert len(gaps) == 1
    assert gaps[0]["km"] == 40
    assert gaps[0]["from_odo"] == 1000 and gaps[0]["to_odo"] == 1040


def test_back_to_back_sessions_leave_no_gap():
    assert gaps_for([_sess(900, 1000, mins=0), _sess(1000, 1100, mins=60)], threshold_km=3) == []


def test_yard_shunting_under_the_threshold_is_ignored():
    # 2 km between withdrawal and next insertion, threshold 3 → not reported.
    assert gaps_for([_sess(900, 1000, mins=0), _sess(1002, 1100, mins=60)], threshold_km=3) == []


def test_crew_overlap_is_covered_not_missing():
    # Two drivers crewing the same stretch: slot 0 covers 1000-1200, slot 1
    # covers 1050-1150 inside it. The high-water mark stays at 1200, so the
    # inner session charges nothing.
    gaps = gaps_for([_sess(1000, 1200, slot=0, mins=0),
                     _sess(1050, 1150, slot=1, mins=30)], threshold_km=3)
    assert gaps == []


def test_a_vehicle_swap_resetting_the_odometer_is_not_counted_as_missing():
    # The replacement unit arrives later in time and reads lower, so it sits
    # under the high-water mark and no forward gap is invented.
    assert gaps_for([_sess(90000, 90500, mins=0), _sess(120, 400, mins=600)], threshold_km=3) == []


def test_duplicate_sessions_from_two_downloads_collapse():
    s = _sess(900, 1000)
    assert len(_dedupe([s, dict(s)])) == 1


def test_merge_joins_overlapping_and_touching_runs():
    merged = _merge([_sess(100, 200), _sess(180, 260), _sess(260, 300)])
    assert len(merged) == 1 and merged[0][0] == 100 and merged[0][1] == 300


def test_missing_km_bands():
    assert mm_band(0) == "green"
    assert mm_band(1) == "amber"
    assert mm_band(49) == "amber"
    assert mm_band(50) == "red"
    assert mm_band(None) == "grey"   # no odometer data is not "clean"

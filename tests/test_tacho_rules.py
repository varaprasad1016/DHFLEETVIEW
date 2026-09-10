"""Unit tests for the drivers' hours / WTD infringement engine."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.services.tacho_rules import (
    Activity, CardGap, PlaceEntry, _duty_days, _prepare, analyse)

UK = 21          # NationNumeric for the United Kingdom

BASE = datetime(2026, 9, 1, 6, 0, 0)  # Tue 06:00


def build(spec: list[tuple[str, int]], start: datetime = BASE) -> list[Activity]:
    """spec = [(type, minutes), ...] -> contiguous activities from `start`."""
    acts, t = [], start
    for typ, mins in spec:
        acts.append(Activity(typ, t, t + timedelta(minutes=mins)))
        t += timedelta(minutes=mins)
    return acts


def rules(infs):
    return {i.rule for i in infs}


def by_rule(infs, rule):
    return [i for i in infs if i.rule == rule]


# --- continuous driving -----------------------------------------------------

def test_continuous_driving_fires_over_4h30():
    infs = analyse(build([("drive", 5 * 60)]))
    assert "continuous_driving" in rules(infs)


def test_continuous_driving_ok_with_45_break():
    infs = analyse(build([("drive", 4 * 60), ("rest", 45), ("drive", 60)]))
    assert "continuous_driving" not in rules(infs)


def test_continuous_driving_ok_with_15_30_split():
    infs = analyse(build([
        ("drive", 2 * 60), ("rest", 15), ("drive", 2 * 60), ("rest", 30), ("drive", 60)]))
    assert "continuous_driving" not in rules(infs)


def test_break_may_be_rest_plus_availability():
    """A break is time not driving and not working, so a 20-min rest running
    into a 25-min period of availability is one 45-minute break."""
    infs = analyse(build([
        ("drive", 4 * 60), ("rest", 20), ("available", 25), ("drive", 60)]))
    assert "continuous_driving" not in rules(infs)


def test_other_work_interrupts_a_break():
    infs = analyse(build([
        ("drive", 4 * 60), ("rest", 25), ("work", 10), ("rest", 25), ("drive", 60)]))
    assert "continuous_driving" in rules(infs)


def test_continuous_driving_reports_the_whole_run():
    infs = by_rule(analyse(build([("drive", 6 * 60)])), "continuous_driving")
    assert infs[0].actual_minutes == 6 * 60


def test_continuous_driving_severity_bands():
    """Directive (EU) 2016/403: under 5h minor, under 6h serious, then very."""
    assert by_rule(analyse(build([("drive", 4 * 60 + 40)])), "continuous_driving")[0].severity == "minor"
    assert by_rule(analyse(build([("drive", 5 * 60 + 30)])), "continuous_driving")[0].severity == "serious"
    assert by_rule(analyse(build([("drive", 6 * 60 + 30)])), "continuous_driving")[0].severity == "very_serious"


# --- the midnight-split regression ------------------------------------------

def test_overnight_rest_is_one_rest_not_two():
    """A driver card holds one record per calendar day, so an 11h overnight rest
    arrives as two spans either side of midnight. They must be merged, or no
    rule ever sees a qualifying daily rest and whole weeks collapse into a
    single "day" with impossible driving totals."""
    day1 = datetime(2026, 6, 8, 5, 0)
    acts = [
        Activity("drive", day1, day1 + timedelta(hours=8)),           # 05:00-13:00
        Activity("rest", day1 + timedelta(hours=8), datetime(2026, 6, 9, 0, 0)),
        Activity("rest", datetime(2026, 6, 9, 0, 0), datetime(2026, 6, 9, 5, 0)),
        Activity("drive", datetime(2026, 6, 9, 5, 0), datetime(2026, 6, 9, 13, 0)),
    ]
    days = _duty_days(_prepare(acts))
    assert len(days) == 2, "the overnight rest must split the two duty days"
    assert days[0].drive == 8 * 60
    assert "daily_driving" not in rules(analyse(acts))


def test_a_week_of_shifts_is_not_one_giant_day():
    """Five 8h driving days with 11h overnight rests: no daily-driving breach."""
    acts = []
    for d in range(8, 13):                       # Mon 08/06 .. Fri 12/06
        start = datetime(2026, 6, d, 5, 0)
        acts.append(Activity("drive", start, start + timedelta(hours=4)))
        acts.append(Activity("rest", start + timedelta(hours=4), start + timedelta(hours=4, minutes=45)))
        acts.append(Activity("drive", start + timedelta(hours=4, minutes=45),
                             start + timedelta(hours=8, minutes=45)))
        acts.append(Activity("rest", start + timedelta(hours=8, minutes=45),
                             datetime(2026, 6, d + 1, 0, 0)))
        acts.append(Activity("rest", datetime(2026, 6, d + 1, 0, 0), datetime(2026, 6, d + 1, 5, 0)))
    days = _duty_days(_prepare(acts))
    assert len(days) == 5
    assert all(d.drive == 8 * 60 for d in days)
    assert "daily_driving" not in rules(analyse(acts))


# --- daily driving ----------------------------------------------------------

def test_daily_driving_over_10h():
    infs = analyse(build([
        ("drive", 4 * 60), ("rest", 45), ("drive", 4 * 60), ("rest", 45), ("drive", 3 * 60)]))
    assert "daily_driving" in rules(infs)


def test_daily_driving_ok_at_9h():
    infs = analyse(build([
        ("drive", 4 * 60), ("rest", 45), ("drive", 4 * 60), ("rest", 11 * 60), ("drive", 60)]))
    assert "daily_driving" not in rules(infs)


def test_daily_driving_severity_bands():
    def sev(hours):
        spec = []
        left = int(hours * 60)
        while left > 0:
            chunk = min(4 * 60, left)
            spec.append(("drive", chunk))
            left -= chunk
            if left:
                spec.append(("rest", 45))
        return by_rule(analyse(build(spec)), "daily_driving")[0].severity
    assert sev(10.5) == "minor"
    assert sev(11.5) == "serious"
    assert sev(12.5) == "very_serious"


# --- daily rest -------------------------------------------------------------

def test_short_daily_rest_is_reported():
    """10h of duty then only 8h rest: a daily rest that is too short, and the
    day ends there rather than swallowing the next one."""
    infs = analyse(build([
        ("drive", 4 * 60), ("rest", 45), ("work", 5 * 60 + 15),
        ("rest", 8 * 60),
        ("work", 8 * 60)]))
    assert "daily_rest_short" in rules(infs)
    assert by_rule(infs, "daily_rest_short")[0].actual_minutes == 8 * 60


def test_daily_rest_not_taken_within_24h():
    """26h of continuous duty with no stop long enough to be a daily rest."""
    spec = []
    for _ in range(13):
        spec += [("work", 100), ("rest", 20)]
    infs = analyse(build(spec))
    assert "daily_rest_24h" in rules(infs)


def test_daily_rest_counted_only_inside_the_24h_window():
    """Start 05:00, finish 18:00, start again 05:30: 11h30 of rest was taken but
    only 11h falls in the 24 hours from duty start, so it is a regular rest -
    and starting again at 05:10 would make it a reduction."""
    def day(next_start_minute):
        acts = build([("work", 13 * 60)], start=datetime(2026, 6, 8, 5, 0))
        rest_end = datetime(2026, 6, 9, 5, 0) + timedelta(minutes=next_start_minute)
        acts.append(Activity("rest", datetime(2026, 6, 8, 18, 0), rest_end))
        acts.append(Activity("work", rest_end, rest_end + timedelta(hours=6)))
        return _duty_days(_prepare(acts))[0].daily_rest
    assert day(30) == 11 * 60          # capped at the 24h window
    assert day(-50) == 10 * 60 + 10    # genuinely shorter, so counted as-is


def test_fourth_reduced_daily_rest_is_reported():
    spec = []
    for _ in range(4):
        spec += [("work", 10 * 60), ("rest", 9 * 60 + 30)]
    infs = analyse(build(spec))
    assert "daily_rest_reduction" in rules(infs)
    assert len(by_rule(infs, "daily_rest_reduction")) == 1


def test_three_reduced_daily_rests_are_allowed():
    spec = []
    for _ in range(3):
        spec += [("work", 10 * 60), ("rest", 9 * 60 + 30)]
    assert "daily_rest_reduction" not in rules(analyse(build(spec)))


# --- weekly -----------------------------------------------------------------

def test_weekly_driving_over_56h():
    # 7 days x 9h driving inside ONE ISO week (Mon 2026-01-05) -> 63h > 56h.
    monday = datetime(2026, 1, 5, 6, 0, 0)
    spec = []
    for _ in range(7):
        spec += [("drive", 4 * 60 + 30), ("rest", 45), ("drive", 4 * 60 + 30), ("rest", 9 * 60)]
    infs = analyse(build(spec, start=monday))
    assert "weekly_driving" in rules(infs)


def test_weekly_rest_must_start_within_six_24h_periods():
    """Eight duty days with only daily rests between them, then a weekly rest."""
    spec = [("rest", 45 * 60)]
    for _ in range(8):
        spec += [("work", 9 * 60), ("rest", 11 * 60)]
    spec[-1] = ("rest", 45 * 60)
    infs = analyse(build(spec))
    assert "weekly_rest_period" in rules(infs)


def test_six_duty_days_then_a_weekly_rest_is_clean():
    spec = [("rest", 45 * 60)]
    for _ in range(5):
        spec += [("work", 9 * 60), ("rest", 11 * 60)]
    spec[-1] = ("rest", 45 * 60)
    assert "weekly_rest_period" not in rules(analyse(build(spec)))


# --- working time -----------------------------------------------------------

def test_wtd_break_over_6h_work():
    infs = analyse(build([("work", 7 * 60)]))
    assert "wtd_break" in rules(infs)


def test_wtd_break_ok_with_30min():
    infs = analyse(build([("work", 6 * 60), ("rest", 30), ("work", 2 * 60)]))
    assert "wtd_break" not in rules(infs)


def test_wtd_pause_counts_from_15_minutes():
    """A 15-minute pause restarts the 6h working-time clock, which is how an
    analyser scores it; requiring 30 raised breaches that were not there."""
    infs = analyse(build([("work", 5 * 60), ("rest", 15), ("work", 5 * 60), ("rest", 30)]))
    assert "wtd_break" not in rules(infs)


def test_availability_counts_as_a_pause():
    infs = analyse(build([("work", 5 * 60), ("available", 45), ("work", 4 * 60)]))
    assert "wtd_break" not in rules(infs)


def test_wtd_total_break_must_reach_30_minutes():
    infs = analyse(build([
        ("work", 3 * 60), ("rest", 17), ("work", 3 * 60 + 10), ("rest", 11 * 60)]))
    assert "wtd_daily_break" in rules(infs)
    assert by_rule(infs, "wtd_daily_break")[0].actual_minutes == 17


def test_wtd_long_day_needs_45_minutes():
    infs = analyse(build([
        ("work", 5 * 60), ("rest", 30), ("work", 5 * 60), ("rest", 11 * 60)]))
    assert "wtd_daily_break" in rules(infs)


# --- country entries and card withdrawals -----------------------------------

def one_day():
    """A single 9h duty day, 05:00-14:00, closed by an 11h rest."""
    return build([("work", 9 * 60), ("rest", 11 * 60)],
                 start=datetime(2026, 6, 8, 5, 0))


def test_missing_country_entries_are_reported():
    infs = analyse(one_day(), places=[])
    assert {"country_start", "country_end"} <= rules(infs)
    assert by_rule(infs, "country_start")[0].severity == "minor"


def test_country_entries_satisfy_the_rule():
    places = [PlaceEntry(datetime(2026, 6, 8, 4, 55), "begin", UK),
              PlaceEntry(datetime(2026, 6, 8, 14, 0), "end", UK)]
    infs = analyse(one_day(), places=places)
    assert "country_start" not in rules(infs)
    assert "country_end" not in rules(infs)


def test_a_place_entry_with_no_country_does_not_count():
    places = [PlaceEntry(datetime(2026, 6, 8, 4, 55), "begin", 0),
              PlaceEntry(datetime(2026, 6, 8, 14, 0), "end", 0)]
    assert "country_start" in rules(analyse(one_day(), places=places))


def test_country_rules_stay_quiet_without_place_data():
    """A caller with only activities must not be told every day is missing its
    country entry - we simply do not know."""
    assert "country_start" not in rules(analyse(one_day()))


def test_unclosed_final_day_is_not_judged_on_its_end():
    """The card was downloaded mid-shift, so the end of that day is unknown."""
    acts = build([("work", 6 * 60)], start=datetime(2026, 6, 8, 5, 0))
    infs = analyse(acts, places=[])
    assert "country_end" not in rules(infs)


def test_card_withdrawn_mid_duty_without_signing_off():
    acts = one_day()
    gap = [CardGap(datetime(2026, 6, 8, 9, 0), datetime(2026, 6, 8, 13, 0))]
    infs = analyse(acts, places=[], card_gaps=gap)
    assert "card_withdrawal" in rules(infs)


def test_card_withdrawal_with_an_end_entry_is_a_normal_sign_off():
    acts = one_day()
    gap = [CardGap(datetime(2026, 6, 8, 9, 0), datetime(2026, 6, 8, 13, 0))]
    places = [PlaceEntry(datetime(2026, 6, 8, 9, 0), "end", UK)]
    assert "card_withdrawal" not in rules(analyse(acts, places=places, card_gaps=gap))


def test_brief_card_withdrawal_is_a_vehicle_change():
    gap = [CardGap(datetime(2026, 6, 8, 9, 0), datetime(2026, 6, 8, 9, 10))]
    assert "card_withdrawal" not in rules(analyse(one_day(), places=[], card_gaps=gap))


def test_card_out_between_duty_periods_is_not_a_withdrawal():
    gap = [CardGap(datetime(2026, 6, 8, 15, 0), datetime(2026, 6, 8, 23, 0))]
    assert "card_withdrawal" not in rules(analyse(one_day(), places=[], card_gaps=gap))


# --- a clean week -----------------------------------------------------------

def test_clean_week_has_no_infringements():
    # 5 days of 8h driving (4+45+4), 11h daily rest -> compliant.
    spec = []
    for _ in range(5):
        spec += [("drive", 4 * 60), ("rest", 45), ("drive", 4 * 60), ("rest", 11 * 60)]
    infs = analyse(build(spec))
    assert rules(infs) == set(), f"unexpected: {[i.rule for i in infs]}"

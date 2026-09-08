"""Unit tests for the drivers' hours / WTD infringement engine."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.services.tacho_rules import Activity, analyse

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


def test_daily_driving_over_10h():
    # 11h driving in a day, broken so continuous never trips.
    infs = analyse(build([
        ("drive", 4 * 60), ("rest", 45), ("drive", 4 * 60), ("rest", 45), ("drive", 3 * 60)]))
    assert "daily_driving" in rules(infs)


def test_daily_driving_ok_at_9h():
    infs = analyse(build([
        ("drive", 4 * 60), ("rest", 45), ("drive", 4 * 60), ("rest", 11 * 60), ("drive", 60)]))
    assert "daily_driving" not in rules(infs)


def test_daily_rest_24h_rule():
    # 10h duty, only 8h rest (does not split the day), then 8h more -> 26h duty span.
    infs = analyse(build([
        ("drive", 4 * 60), ("rest", 45), ("work", 5 * 60 + 15),   # 10h duty
        ("rest", 8 * 60),                                          # sub-9h, no split
        ("work", 8 * 60)]))
    assert "daily_rest_24h" in rules(infs)


def test_wtd_break_over_6h_work():
    infs = analyse(build([("work", 7 * 60)]))
    assert "wtd_break" in rules(infs)


def test_wtd_break_ok_with_30min():
    infs = analyse(build([("work", 6 * 60), ("rest", 30), ("work", 2 * 60)]))
    assert "wtd_break" not in rules(infs)


def test_weekly_driving_over_56h():
    # 7 days x 9h driving inside ONE ISO week (Mon 2026-01-05) -> 63h > 56h.
    monday = datetime(2026, 1, 5, 6, 0, 0)
    spec = []
    for _ in range(7):
        spec += [("drive", 4 * 60 + 30), ("rest", 45), ("drive", 4 * 60 + 30), ("rest", 9 * 60)]
    infs = analyse(build(spec, start=monday))
    assert "weekly_driving" in rules(infs)


def test_clean_week_has_no_infringements():
    # 5 days of 8h driving (4+45+4), 11h daily rest -> compliant.
    spec = []
    for _ in range(5):
        spec += [("drive", 4 * 60), ("rest", 45), ("drive", 4 * 60), ("rest", 11 * 60)]
    infs = analyse(build(spec))
    assert rules(infs) == set(), f"unexpected: {[i.rule for i in infs]}"

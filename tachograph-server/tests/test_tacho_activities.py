"""Tests for the canonical tachograph activity projection."""

from datetime import datetime, timezone

from app.api.tacho import _same_registration, _vehicle_ref_for
from app.services.ddd_parser import VehiclePeriod
from app.services.tacho_rules import Activity

UTC = timezone.utc


def test_vu_registration_matching_ignores_spaces_and_case():
    assert _same_registration("ab 12 cde", "AB12CDE")
    assert not _same_registration("AB12CDE", "AB12CDF")


def test_activity_uses_vehicle_spell_from_card():
    activity = Activity("drive", datetime(2026, 6, 22, 9, tzinfo=UTC),
                        datetime(2026, 6, 22, 10, tzinfo=UTC))
    parsed = {"vehicles": [VehiclePeriod(
        "FY69OXM", 0, datetime(2026, 6, 22, 8, tzinfo=UTC),
        datetime(2026, 6, 22, 12, tzinfo=UTC), 100, 150)]}
    assert _vehicle_ref_for(parsed, activity) == "FY69OXM"


def test_activity_falls_back_to_assigned_vehicle():
    activity = Activity("work", datetime(2026, 6, 22, 9, tzinfo=UTC),
                        datetime(2026, 6, 22, 10, tzinfo=UTC))
    assert _vehicle_ref_for({"vehicles": []}, activity, "PN19HNR") == "PN19HNR"


def test_activity_does_not_use_a_vehicle_spell_before_it_started():
    activity = Activity("rest", datetime(2026, 6, 22, 7, tzinfo=UTC),
                        datetime(2026, 6, 22, 8, tzinfo=UTC))
    parsed = {"vehicles": [VehiclePeriod(
        "FY69OXM", 0, datetime(2026, 6, 22, 9, tzinfo=UTC), None, 100, None)]}
    assert _vehicle_ref_for(parsed, activity, "PN19HNR") == "PN19HNR"

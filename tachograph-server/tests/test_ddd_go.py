"""Tests for the optional tachograph-go parser adapter."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services import ddd_go
from app.services.tacho_rules import Activity, PlaceEntry


UTC = timezone.utc


def test_activity_records_are_mapped_to_normalised_spans():
    document = {
        "driverCard": {
            "tachograph": {
                "driverActivityData": {
                    "dailyRecords": [{
                        "activityRecordDate": "2026-06-08T00:00:00Z",
                        "activityChangeInfo": [
                            {"slot": "DRIVER_SLOT", "activity": "DRIVING",
                             "timeOfChangeMinutes": 60, "inserted": True},
                            {"slot": "DRIVER_SLOT", "activity": "WORK",
                             "timeOfChangeMinutes": 180, "inserted": True},
                            {"slot": "DRIVER_SLOT", "activity": "BREAK_REST",
                             "timeOfChangeMinutes": 240, "inserted": True},
                        ],
                    }]
                },
                "places": {"records": []},
                "vehiclesUsed": {"records": []},
                "eventsData": {"events": []},
                "faultsData": {"faults": []},
                "identification": {
                    "cardHolderSurname": {"value": "DOE"},
                    "cardHolderFirstNames": {"value": "JANE"},
                    "driverIdentification": {
                        "driverIdentificationNumber": {"value": "UK123"},
                        "cardReplacementIndex": {"value": "0"},
                        "cardRenewalIndex": {"value": "1"},
                    },
                },
            }
        }
    }

    original = ddd_go._run
    try:
        ddd_go._run = lambda _data: document
        parsed = ddd_go.parse_driver_card(b"card")
    finally:
        ddd_go._run = original

    assert [(a.type, a.start.hour, a.end.hour) for a in parsed["activities"]] == [
        ("drive", 1, 3), ("work", 3, 4)
    ]
    assert parsed["driver_name"] == "DOE JANE"
    assert parsed["card_number"] == "UK12301"
    assert parsed["parser"] == "tachograph-go"


def test_place_country_name_satisfies_country_presence():
    result = ddd_go._places({"records": [
        {"entryTime": "2026-06-08T04:55:00Z",
         "entryTypeDailyWorkPeriod": "BEGINNING_OF_DAY",
         "dailyWorkPeriodCountry": "UNITED_KINGDOM"},
        {"entryTime": "2026-06-08T14:00:00Z",
         "entryTypeDailyWorkPeriod": "END_OF_DAY",
         "dailyWorkPeriodCountry": "NO_INFORMATION"},
    ]})
    assert len(result) == 2
    assert isinstance(result[0], PlaceEntry)
    assert result[0].country == 0
    assert result[0].country_name == "UNITED_KINGDOM"
    assert result[0].has_country
    assert result[1].country_name == ""
    assert not result[1].has_country


def test_failed_go_parse_falls_back_when_enabled(monkeypatch):
    from app.api import tacho
    from app.config import settings

    monkeypatch.setattr(settings, "tacho_parser_enabled", True)
    monkeypatch.setattr(settings, "tacho_parser_fallback", True)
    monkeypatch.setattr(ddd_go, "available", lambda: True)
    monkeypatch.setattr(ddd_go, "parse_driver_card",
                        lambda _data: (_ for _ in ()).throw(RuntimeError("bad Go output")))
    fallback = {"activities": [Activity("rest", datetime(2026, 1, 1),
                                         datetime(2026, 1, 1, 1))]}
    monkeypatch.setattr(tacho.ddd_parser, "parse_driver_card", lambda _data: fallback)

    parsed, parser = tacho._parse_driver_card(b"card")
    assert parsed is fallback
    assert parser == "builtin-gen1"


def test_failed_go_parse_is_fatal_when_fallback_disabled(monkeypatch):
    from app.api import tacho
    from app.config import settings

    monkeypatch.setattr(settings, "tacho_parser_enabled", True)
    monkeypatch.setattr(settings, "tacho_parser_fallback", False)
    monkeypatch.setattr(ddd_go, "available", lambda: True)
    monkeypatch.setattr(ddd_go, "parse_driver_card",
                        lambda _data: (_ for _ in ()).throw(RuntimeError("bad Go output")))

    with pytest.raises(RuntimeError, match="bad Go output"):
        tacho._parse_driver_card(b"card")

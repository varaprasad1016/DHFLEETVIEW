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


def test_vehicle_unit_metadata_and_activity_mapping(monkeypatch):
    document = {
        "type": "VEHICLE_UNIT",
        "vehicleUnit": {
            "gen1": {
                "overview": {
                    "vehicleIdentificationNumber": {"value": "WF0XXXTTGX1234567"},
                    "vehicleRegistrationWithNation": {
                        "number": {"value": "AB12CDE"}
                    },
                },
                "technicalData": [{
                    "vuIdentification": {"serialNumber": {"serialNumber": 12345678}}
                }],
                "activities": [{
                    "dateOfDay": "2026-06-22T00:00:00Z",
                    "activityChanges": [
                        {"slot": "DRIVER_SLOT", "activity": "DRIVING",
                         "timeOfChangeMinutes": 60, "inserted": True},
                        {"slot": "DRIVER_SLOT", "activity": "WORK",
                         "timeOfChangeMinutes": 180, "inserted": True},
                        {"slot": "DRIVER_SLOT", "activity": "BREAK_REST",
                         "timeOfChangeMinutes": 240, "inserted": True},
                    ],
                }],
            }
        },
    }
    monkeypatch.setattr(ddd_go, "_run", lambda _data: document)

    parsed = ddd_go.parse_vehicle_unit(b"vehicle-unit")

    assert parsed["file_type"] == "vehicle_unit"
    assert parsed["parser"] == "tachograph-go"
    assert parsed["vehicle_ref"] == "AB12CDE"
    assert parsed["vehicle_vin"] == "WF0XXXTTGX1234567"
    assert parsed["tachograph_serial"] == "12345678"
    assert [(a.type, a.start.hour, a.end.hour) for a in parsed["activities"]] == [
        ("drive", 1, 3), ("work", 3, 4)
    ]
    assert parsed["activity_driver_refs"] == [None, None]


def test_vehicle_unit_accepts_protojson_snake_case_and_numeric_enums(monkeypatch):
    document = {
        "vehicle_unit": {"gen1": {
            "overview": {"vehicle_registration_with_nation": {
                "number": {"value": "ZZ99YYY"}
            }},
            "activities": [{
                "date_of_day": "2026-06-23T00:00:00Z",
                "activity_changes": [
                    {"slot": 0, "activity": 5, "time_of_change_minutes": 0},
                    {"slot": 0, "activity": 4, "time_of_change_minutes": 30},
                ],
            }],
        }}
    }
    monkeypatch.setattr(ddd_go, "_run", lambda _data: document)

    parsed = ddd_go.parse_vehicle_unit(b"vehicle-unit")

    assert parsed["vehicle_ref"] == "ZZ99YYY"
    assert [(a.type, a.start.minute, a.end.minute) for a in parsed["activities"]] == [
        ("drive", 0, 30)
    ]


def test_vehicle_unit_rejects_a_driver_card_document(monkeypatch):
    monkeypatch.setattr(ddd_go, "_run", lambda _data: {"driverCard": {}})

    with pytest.raises(ValueError, match="not a vehicle-unit file"):
        ddd_go.parse_vehicle_unit(b"driver-card")


def test_upload_batch_returns_one_result_per_file(monkeypatch):
    from app.api import tacho

    async def fake_upload(item, session=None, x_company_id=None):
        return {"filename": item.filename, "parsed": item.filename == "good.ddd"}

    monkeypatch.setattr(tacho, "upload", fake_upload)
    body = [
        tacho.UploadIn(filename="good.ddd", content_base64="YQ=="),
        tacho.UploadIn(filename="bad.ddd", content_base64="Yg=="),
    ]

    import asyncio
    result = asyncio.run(tacho.upload_batch(body, session=object()))

    assert result["total"] == 2
    assert result["successful"] == 2
    assert [item["filename"] for item in result["files"]] == ["good.ddd", "bad.ddd"]


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

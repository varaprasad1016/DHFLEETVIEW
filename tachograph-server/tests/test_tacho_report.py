"""Tests for the weekly report builder and its PDF rendering."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.services.ddd_parser import CardIncident, VehiclePeriod
from app.services.tacho_pdf import render
from app.services.tacho_report import build_report, hhmm
from app.services.tacho_rules import Activity, Infringement

UTC = timezone.utc


def at(day: int, hour: int, minute: int = 0, month: int = 6) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


def shift(day: int, start_hour: int, drive_hours: int, work_hours: int = 2,
          month: int = 6) -> list[Activity]:
    """A day's work in UTC: drive, then other work, then rest to the next day."""
    t = at(day, start_hour, month=month)
    acts = [Activity("drive", t, t + timedelta(hours=drive_hours))]
    t = acts[-1].end
    acts.append(Activity("work", t, t + timedelta(hours=work_hours)))
    acts.append(Activity("rest", acts[-1].end, at(day + 1, start_hour, month=month)))
    return acts


def parsed(acts, vehicles=None, incidents=None):
    return {"activities": acts, "places": [], "card_gaps": [],
            "vehicles": vehicles or [], "incidents": incidents or [],
            "driver_name": "TEST DRIVER", "card_number": "UK123",
            "driver_ref": "TEST DRIVER"}


def rows_of(report):
    return [r for week in report["weeks"] for r in week["days"]]


def test_hhmm_runs_past_a_day():
    assert hhmm(84 * 60 + 11) == "84:11"
    assert hhmm(None) == ""


def test_a_day_is_cut_on_local_midnight_not_utc():
    """British Summer Time is an hour ahead, so work between 23:00 and 24:00 UTC
    belongs to the next day's report row."""
    acts = [Activity("drive", at(8, 22, 30), at(8, 23, 30))]   # 23:30-00:30 local
    report = build_report(parsed(acts), [], start=date(2026, 6, 8), end=date(2026, 6, 9))
    by_date = {r["date"]: r["drive"] for r in rows_of(report)}
    assert by_date["2026-06-08"] == 30
    assert by_date["2026-06-09"] == 30


def test_wtd_column_is_duty_time_including_availability():
    acts = [Activity("drive", at(8, 5), at(8, 9)),
            Activity("work", at(8, 9), at(8, 10)),
            Activity("available", at(8, 10), at(8, 12)),
            Activity("rest", at(8, 12), at(9, 6))]
    row = rows_of(build_report(parsed(acts), [], start=date(2026, 6, 8),
                               end=date(2026, 6, 8)))[0]
    assert row["drive"] == 240 and row["work"] == 60 and row["poa"] == 120
    assert row["wtd"] == 420


def test_break_is_rest_inside_the_duty_period_only():
    acts = [Activity("drive", at(8, 5), at(8, 9)),
            Activity("rest", at(8, 9), at(8, 10)),        # a break
            Activity("drive", at(8, 10), at(8, 13)),
            Activity("rest", at(8, 13), at(9, 5))]        # the daily rest
    row = rows_of(build_report(parsed(acts), [], start=date(2026, 6, 8),
                               end=date(2026, 6, 8)))[0]
    assert row["break"] == 60


def test_fortnight_drive_counts_the_week_before_the_report():
    """A report starting on a Monday still has to know what the driver drove the
    week before, which is not on the page."""
    acts = []
    for day in (1, 2, 3, 4, 5):                 # Mon 01/06 .. Fri 05/06
        acts += shift(day, 5, drive_hours=4)
    for day in (8, 9):                          # the week the report shows
        acts += shift(day, 5, drive_hours=3)
    report = build_report(parsed(acts), [], start=date(2026, 6, 8), end=date(2026, 6, 9))
    rows = rows_of(report)
    assert rows[0]["fortnight_drive"] == (5 * 4 + 3) * 60
    assert rows[1]["fortnight_drive"] == (5 * 4 + 3 + 3) * 60


def test_a_vehicle_record_counts_for_one_day_only():
    """Records are cut at UTC midnight, an hour adrift of the local day, so a
    record must not lend its mileage to the day before."""
    acts = shift(8, 5, drive_hours=4) + shift(9, 5, drive_hours=4)
    vehicles = [
        VehiclePeriod("AB12 CDE", 21, at(8, 4), at(8, 23, 59), 1000, 1400),
        VehiclePeriod("AB12 CDE", 21, at(9, 0), at(9, 23, 59), 1400, 1900),
    ]
    rows = {r["date"]: r for r in rows_of(build_report(
        parsed(acts, vehicles), [], start=date(2026, 6, 8), end=date(2026, 6, 9)))}
    assert rows["2026-06-08"]["distance"] == 400
    assert rows["2026-06-09"]["distance"] == 500
    assert rows["2026-06-09"]["odometer_start"] == 1400


def test_days_beyond_the_download_are_marked_as_having_no_data():
    acts = shift(8, 5, drive_hours=4)
    rows = {r["date"]: r for r in rows_of(build_report(
        parsed(acts), [], start=date(2026, 6, 8), end=date(2026, 6, 12)))}
    assert rows["2026-06-08"]["no_data"] is False
    assert rows["2026-06-11"]["no_data"] is True
    assert rows["2026-06-11"]["rest_day"] is False


def test_an_unfinished_shift_has_no_end_time_or_daily_rest():
    acts = [Activity("drive", at(8, 5), at(8, 9))]      # card downloaded mid-shift
    row = rows_of(build_report(parsed(acts), [], start=date(2026, 6, 8),
                               end=date(2026, 6, 8)))[0]
    assert row["end_duty"] == "" and row["shift"] is None and row["daily_rest"] is None


def test_findings_are_split_into_working_time_and_the_rest():
    acts = shift(8, 5, drive_hours=4)
    infs = [
        Infringement("wtd_break", "Over 6h working time without a break", "serious",
                     at(8, 6), at(8, 12), "detail", 360, 400),
        Infringement("daily_driving", "Daily driving over 10h", "very_serious",
                     at(8, 5), at(8, 18), "detail", 600, 700),
    ]
    week = build_report(parsed(acts), infs, start=date(2026, 6, 8),
                        end=date(2026, 6, 8))["weeks"][0]
    assert [i["rule"] for i in week["working_time_infringements"]] == ["wtd_break"]
    assert [i["rule"] for i in week["infringements"]] == ["daily_driving"]


def test_faults_reach_the_report():
    acts = shift(8, 5, drive_hours=4)
    incident = CardIncident("fault", 0x31, "Tachograph fault", at(8, 7), at(8, 8), "AB12 CDE")
    week = build_report(parsed(acts, incidents=[incident]), [],
                        start=date(2026, 6, 8), end=date(2026, 6, 8))["weeks"][0]
    assert week["faults"][0]["name"] == "Tachograph fault"


def test_pdf_renders_one_page_per_week():
    pypdf = __import__("pypdf")
    acts = []
    for day in (8, 9, 10, 15, 16):
        acts += shift(day, 5, drive_hours=4)
    report = build_report(parsed(acts), [], start=date(2026, 6, 8), end=date(2026, 6, 21))
    pdf = render(report)
    assert pdf.startswith(b"%PDF")
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    assert len(reader.pages) == len(report["weeks"]) == 2
    assert "TEST DRIVER" in reader.pages[0].extract_text()


def test_pdf_copes_with_an_empty_period():
    pdf = render({"driver": {}, "period": {}, "weeks": []})
    assert pdf.startswith(b"%PDF")

"""The mapping from tachoparser's JSON onto our own activity model.

These work on hand-written records rather than real downloads: a real DDD
carries a named driver's card number, birth date and movements, and none of
that belongs in a repository. The shapes here are the ones the parser actually
emits, taken from its Go struct tags.
"""

from datetime import date, datetime, timezone

from app.services import ddd_traconiq as parser
from app.services.tacho_rules import Activity as Activity_


def _change(minute, work_type, *, card_present=True, driver=True, team=False):
    return {"driver": driver, "team": team, "card_present": card_present,
            "work_type": work_type, "minutes": minute}


def _at(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class TestActivityChanges:
    def test_the_four_activities_are_recognised(self):
        changes = parser._changes([
            _change(0, 0), _change(10, 1), _change(20, 2), _change(30, 3)])
        assert [kind for _, kind, _, _ in changes] == [
            "rest", "available", "work", "drive"]

    def test_records_are_put_back_into_time_order(self):
        changes = parser._changes([_change(100, 3), _change(5, 2)])
        assert [minute for minute, *_ in changes] == [5, 100]

    def test_an_unknown_activity_is_dropped_not_guessed(self):
        assert parser._changes([_change(0, 9)]) == []

    def test_a_minute_outside_the_day_is_dropped(self):
        assert parser._changes([_change(1441, 3), _change(-1, 3)]) == []

    def test_the_multi_manning_bit_is_what_marks_crewing(self):
        """`team`, not the slot.

        An empty second seat still records a change of its own, so reading the
        slot as crewing marks a lorry with nobody in seat two as two-up. The
        regulation's `team` bit is set on both seats' records while a shift is
        genuinely crewed, which is also what the rest rules need: multi-manned
        work is rested 9 hours inside 30, and that applies to both drivers.
        """
        (_, _, _, crew), = parser._changes([_change(0, 3, team=True)])
        assert crew is True

    def test_the_second_seat_alone_is_not_crewing(self):
        (_, _, _, crew), = parser._changes([_change(0, 3, driver=False, team=False)])
        assert crew is False

    def test_single_manned_work_is_not_crewing(self):
        (_, _, _, crew), = parser._changes([_change(0, 3, driver=True)])
        assert crew is False

    def test_a_card_that_was_out_is_flagged(self):
        (_, _, card_out, _), = parser._changes([_change(0, 0, card_present=False)])
        assert card_out is True


class TestSpans:
    def test_a_finished_day_is_covered_minute_for_minute(self):
        """A card's daily record runs midnight to midnight.

        This is the behaviour the older tachograph-go reader lost: it dropped
        the record in force at 00:00 and so lost the overnight rest, leaving
        the day hundreds of minutes short.
        """
        day = _at(2026, 5, 20)
        activities, _ = parser._spans([
            (day, parser._changes([_change(0, 0), _change(207, 2), _change(300, 3)])),
            # A second, newer day so the first is treated as finished.
            (_at(2026, 5, 21), parser._changes([_change(0, 0), _change(60, 3)])),
        ])
        first_day = [a for a in activities if a.start.date() == date(2026, 5, 20)]
        assert sum(a.minutes for a in first_day) == 1440
        assert first_day[0].type == "rest"
        assert first_day[0].start == day
        assert first_day[0].minutes == 207

    def test_the_newest_days_last_activity_is_not_run_to_midnight(self):
        """The download happened part way through the newest day.

        Closing that activity at midnight would credit hours that had not
        happened yet when the file was written.
        """
        activities, _ = parser._spans([
            (_at(2026, 5, 20), parser._changes([_change(0, 0), _change(600, 3)])),
        ])
        assert len(activities) == 1
        assert activities[0].type == "rest"
        assert activities[0].end == _at(2026, 5, 20, 10)

    def test_a_day_with_one_record_and_a_day_after_it_is_a_full_rest_day(self):
        activities, _ = parser._spans([
            (_at(2026, 5, 20), parser._changes([_change(0, 0)])),
            (_at(2026, 5, 21), parser._changes([_change(0, 0), _change(60, 3)])),
        ])
        assert activities[0].minutes == 1440
        assert activities[0].type == "rest"

    def test_an_activity_that_ends_where_it_starts_is_dropped(self):
        activities, _ = parser._spans([
            (_at(2026, 5, 20), parser._changes([_change(10, 3), _change(10, 2)])),
            (_at(2026, 5, 21), parser._changes([_change(0, 0), _change(60, 3)])),
        ])
        assert all(a.minutes > 0 for a in activities)

    def test_touching_card_out_periods_become_one_gap(self):
        _, gaps = parser._spans([
            (_at(2026, 5, 20), parser._changes([
                _change(0, 0, card_present=False),
                _change(100, 2, card_present=False),
                _change(200, 3)])),
            (_at(2026, 5, 21), parser._changes([_change(0, 0), _change(60, 3)])),
        ])
        assert len(gaps) == 1
        assert gaps[0].start == _at(2026, 5, 20)
        assert gaps[0].minutes == 200

    def test_separated_card_out_periods_stay_separate(self):
        _, gaps = parser._spans([
            (_at(2026, 5, 20), parser._changes([
                _change(0, 0, card_present=False),
                _change(60, 2),
                _change(120, 0, card_present=False),
                _change(180, 3)])),
            (_at(2026, 5, 21), parser._changes([_change(0, 0), _change(60, 3)])),
        ])
        assert len(gaps) == 2


class TestSlots:
    """A vehicle unit writes both seats into one list. They are two people."""

    def test_each_seat_gets_its_own_timeline(self):
        slots = parser._changes_by_slot([
            _change(0, 0, driver=True), _change(60, 3, driver=True),
            _change(0, 1, driver=False, card_present=False),
        ])
        assert sorted(slots) == [0, 1]
        assert len(slots[0]) == 2
        assert len(slots[1]) == 1

    def test_one_seats_break_is_not_closed_by_the_others_change(self):
        """The bug this guards against.

        Merged into one sequence, the driver's rest from 00:00 is cut short at
        00:30 by the co-driver's change, and a shift comes out with no break in
        it. Kept apart, the driver's rest runs its full hour.
        """
        slots = parser._changes_by_slot([
            _change(0, 0, driver=True), _change(60, 2, driver=True),
            _change(30, 2, driver=False),
        ])
        spans, _gaps = parser._spans([(_at(2026, 5, 20), slots[0])])
        rest = [a for a in spans if a.type == "rest"]
        assert rest[0].minutes == 60


class TestAttribution:
    """Whose hours a span is, when a card comes out part way through it."""

    def _cards(self, *sessions):
        return [(0, who, start, end) for who, start, end in sessions]

    def test_a_span_is_cut_at_the_card_withdrawal(self):
        """The bug this guards against.

        With no card in, the unit books the seat as work to midnight. Handing
        that whole span to the driver who left at 11:21 invents an afternoon
        shift, and the rules then report a duty period with no rest in it.
        """
        span = Activity_("work", _at(2026, 5, 20, 10), _at(2026, 5, 21))
        pieces = parser._attribute(span, 0, self._cards(
            ("A DRIVER", _at(2026, 5, 20, 6), _at(2026, 5, 20, 11, 21))))
        assert [(p.start.strftime("%H:%M"), p.end.strftime("%H:%M"), who)
                for p, who in pieces] == [
            ("10:00", "11:21", "A DRIVER"), ("11:21", "00:00", None)]

    def test_time_before_a_card_went_in_belongs_to_nobody(self):
        span = Activity_("work", _at(2026, 5, 20, 6), _at(2026, 5, 20, 12))
        pieces = parser._attribute(span, 0, self._cards(
            ("A DRIVER", _at(2026, 5, 20, 8), _at(2026, 5, 20, 12))))
        assert [who for _, who in pieces] == [None, "A DRIVER"]

    def test_a_card_still_in_the_unit_holds_the_span_to_its_end(self):
        span = Activity_("drive", _at(2026, 5, 20, 6), _at(2026, 5, 20, 9))
        pieces = parser._attribute(span, 0, self._cards(
            ("A DRIVER", _at(2026, 5, 20, 5), None)))
        assert len(pieces) == 1
        assert pieces[0][1] == "A DRIVER"
        assert pieces[0][0].minutes == 180

    def test_a_sliver_left_by_a_mid_minute_withdrawal_is_not_a_period_of_work(self):
        span = Activity_("work", _at(2026, 5, 20, 11, 21), _at(2026, 5, 21))
        withdrawn = _at(2026, 5, 20, 11, 21).replace(second=33)
        pieces = parser._attribute(span, 0, self._cards(
            ("A DRIVER", _at(2026, 5, 20, 6), withdrawn)))
        assert [who for _, who in pieces] == [None]

    def test_a_span_nobody_was_aboard_for_belongs_to_nobody(self):
        span = Activity_("work", _at(2026, 5, 20, 6), _at(2026, 5, 20, 9))
        assert [who for _, who in parser._attribute(span, 0, [])] == [None]

    def test_the_other_seats_card_does_not_claim_this_seats_span(self):
        span = Activity_("drive", _at(2026, 5, 20, 6), _at(2026, 5, 20, 9))
        cards = [(1, "CO DRIVER", _at(2026, 5, 20, 5), None)]
        assert [who for _, who in parser._attribute(span, 0, cards)] == [None]


class TestPlaces:
    def test_an_even_entry_type_begins_a_period_and_an_odd_one_ends_it(self):
        places = parser._places([
            {"place_record": {"entry_time": "2026-05-09T06:00:00Z",
                              "entry_type_daily_work_period": 0,
                              "daily_work_period_country": 21}},
            {"place_record": {"entry_time": "2026-05-09T18:00:00Z",
                              "entry_type_daily_work_period": 3,
                              "daily_work_period_country": 21}},
        ])
        assert [p.kind for p in places] == ["begin", "end"]
        assert all(p.has_country for p in places)

    def test_an_unset_country_is_not_treated_as_an_entry(self):
        place, = parser._places([
            {"place_record": {"entry_time": "2026-05-09T06:00:00Z",
                              "entry_type_daily_work_period": 0,
                              "daily_work_period_country": 0xFF}}])
        assert place.has_country is False

    def test_empty_ring_slots_are_skipped(self):
        assert parser._places([{"place_record": {"entry_time": None}}, {}]) == []


class TestTimes:
    def test_a_tachograph_with_a_flat_battery_is_not_a_date(self):
        assert parser._time("0000-01-01T00:00:00Z") is None

    def test_a_real_stamp_comes_back_in_utc(self):
        assert parser._time("2026-05-09T06:00:00Z") == _at(2026, 5, 9, 6)

    def test_nothing_is_not_a_date(self):
        assert parser._time(None) is None
        assert parser._time("") is None
        assert parser._time(12345) is None


class TestOdometer:
    def test_an_unset_odometer_is_not_a_reading(self):
        assert parser._odometer(0xFFFFFF) is None
        assert parser._odometer(0) is None

    def test_a_real_reading_is_kept(self):
        assert parser._odometer(752642) == 752642


class TestGenerationChoice:
    def test_the_newest_generation_with_activity_wins(self):
        suffix, label = parser._vu_generation({
            "vu_overview_1": {"x": 1}, "vu_activities_1": [{}],
            "vu_overview_2": {"x": 1}, "vu_activities_2": [{}]})
        assert (suffix, label) == ("_2", "GENERATION_2_VERSION_1")

    def test_a_file_with_no_activity_still_identifies_the_vehicle(self):
        suffix, _ = parser._vu_generation({"vu_overview_1": {"x": 1}})
        assert suffix == "_1"

    def test_an_empty_document_is_refused(self):
        import pytest
        with pytest.raises(ValueError):
            parser._vu_generation({})


class TestRecordArrays:
    def test_a_second_generation_record_array_is_unwrapped(self):
        assert parser._records({"a": {"records": [1, 2]}}, "a") == [1, 2]

    def test_a_first_generation_plain_list_is_taken_as_is(self):
        assert parser._records({"a": [1, 2]}, "a") == [1, 2]

    def test_a_missing_block_is_no_records_rather_than_an_error(self):
        assert parser._records({}, "a") == []
        assert parser._records(None, "a") == []

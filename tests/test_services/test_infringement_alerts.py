"""The Monday texts to drivers.

The part that would go wrong quietly is who gets texted: a driver must only
ever hear about infringements on their own card, a signed one must not be
nagged about, and a rule the office has switched off everywhere must not reach
a driver's phone when it never reaches the office's report.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.services.infringement_alerts import Alert, card_key, message, plan

MONDAY = datetime(2026, 11, 9, tzinfo=timezone.utc)


def _acct(name="Jo Bloggs", phone="07700900123", card="DB1234567890120X", active=True):
    return (uuid.uuid4(), name, phone, card, active)


def _inf(ref="BLOGGS JO", rule="daily_drive", status="open", when=MONDAY + timedelta(days=2)):
    return (uuid.uuid4(), ref, rule, status, when)


def test_card_key_compares_on_the_fourteen_character_identification():
    assert card_key("db1234567890120x") == "DB123456789012"
    assert card_key("DB12 3456 7890 12 0X") == "DB123456789012"
    assert card_key(None) == ""


def test_a_driver_with_a_new_unsigned_infringement_is_texted():
    acct = _acct()
    inf = _inf()
    alerts = plan([acct], {"DB123456789012": {"BLOGGS JO"}}, [inf], set(), set(), MONDAY)
    assert len(alerts) == 1
    assert alerts[0].name == "Jo Bloggs"
    assert alerts[0].new == 1 and alerts[0].outstanding == 1


def test_older_unsigned_ones_count_as_outstanding_not_new():
    acct = _acct()
    infs = [_inf(), _inf(when=MONDAY - timedelta(days=20)), _inf(when=MONDAY - timedelta(days=40))]
    [alert] = plan([acct], {"DB123456789012": {"BLOGGS JO"}}, infs, set(), set(), MONDAY)
    assert (alert.new, alert.outstanding) == (1, 3)


def test_signed_dismissed_and_hidden_infringements_are_not_mentioned():
    acct = _acct()
    signed = _inf()
    dismissed = _inf(status="dismissed")
    hidden = _inf(rule="country_start")
    alerts = plan([acct], {"DB123456789012": {"BLOGGS JO"}}, [signed, dismissed, hidden],
                  {signed[0]}, {"country_start"}, MONDAY)
    assert alerts == []


def test_only_the_cards_own_infringements_reach_a_driver():
    jo = _acct()
    sam = _acct(name="Sam Smith", phone="07700900999", card="DB9999999999990X")
    infs = [_inf(ref="BLOGGS JO"), _inf(ref="SMITH SAM"), _inf(ref="SMITH SAM")]
    refs = {"DB123456789012": {"BLOGGS JO"}, "DB999999999999": {"SMITH SAM"}}
    alerts = {a.name: a for a in plan([jo, sam], refs, infs, set(), set(), MONDAY)}
    assert alerts["Jo Bloggs"].outstanding == 1
    assert alerts["Sam Smith"].outstanding == 2


def test_inactive_logins_and_logins_without_a_card_number_are_left_alone():
    gone = _acct(active=False)
    no_card = _acct(name="No Card", card="")
    short = _acct(name="Short", card="DB12")
    alerts = plan([gone, no_card, short], {"DB123456789012": {"BLOGGS JO"}}, [_inf()],
                  set(), set(), MONDAY)
    assert alerts == []


def test_a_login_without_a_phone_is_still_planned_so_it_can_be_reported_as_skipped():
    acct = _acct(phone="  ")
    [alert] = plan([acct], {"DB123456789012": {"BLOGGS JO"}}, [_inf()], set(), set(), MONDAY)
    assert alert.phone is None


def test_the_text_says_what_is_new_what_is_waiting_and_where_to_go():
    both = message(Alert(uuid.uuid4(), "Jo Bloggs", "07700900123", new=2, outstanding=3))
    assert both.startswith("DH FleetView: Jo, you have 2 new drivers' hours infringements from last week "
                           "and 1 older one still waiting.")
    assert both.endswith("/driver#/infringements")

    reminder = message(Alert(uuid.uuid4(), "Jo Bloggs", "07700900123", new=0, outstanding=1))
    assert "1 drivers' hours infringement still waiting for your signature" in reminder
    assert "new" not in reminder


def test_the_text_fits_in_two_sms_parts():
    long_name = "Bartholomew-Fitzgerald " * 4
    assert len(message(Alert(uuid.uuid4(), long_name, "0", new=12, outstanding=40))) <= 300

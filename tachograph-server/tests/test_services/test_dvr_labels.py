"""What the numbers on a DVR label are taken to mean.

The label carries several barcodes and no indication of which is which, so each
value is recognised by its own shape. These are the shapes seen on the labels of
the cameras actually fitted to the fleet.
"""

from __future__ import annotations

from app.services.dvr_labels import classify


def test_each_number_is_recognised_by_its_shape():
    fields = classify(["0442607280004", "044270960004", "07940732211", "335339467059"])
    assert fields["device_id"] == "044270960004"     # 12 digits, leading zero
    assert fields["serial"] == "0442607280004"       # 13 digits
    assert fields["mobile_no"] == "07940732211"      # a UK mobile number
    assert fields["sim_no"] == "335339467059"        # what is left is the SIM


def test_the_order_the_barcodes_are_read_in_does_not_matter():
    """A photo taken upside down reads the same label."""
    values = ["335339467059", "07940732211", "044270960004", "0442607280004"]

    def sorted_fields(read):
        return {k: v for k, v in read.items() if k != "barcodes"}

    assert sorted_fields(classify(values)) == sorted_fields(classify(list(reversed(values))))


def test_a_printed_registration_is_picked_up_when_there_is_one():
    fields = classify(["NX71 SCV", "044270960004"])
    assert fields["registration"] == "NX71SCV"


def test_a_label_that_read_badly_leaves_the_fields_empty():
    fields = classify(["", "???"])
    assert fields["device_id"] is None
    assert fields["sim_no"] is None
    assert fields["registration"] is None


def test_the_device_id_is_never_mistaken_for_the_sim():
    """Both are long digit strings; only the device ID starts with a zero."""
    fields = classify(["044270960004", "8944123456789012345"])
    assert fields["device_id"] == "044270960004"
    assert fields["sim_no"] == "8944123456789012345"

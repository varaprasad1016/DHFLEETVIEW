"""What the numbers on a DVR label are taken to mean.

The label carries several barcodes and no indication of which is which, so each
value is recognised by its own shape. These are the shapes seen on the labels of
the cameras actually fitted to the fleet.
"""

from __future__ import annotations

from app.services.dvr_labels import classify


# The four barcodes on a real HZ-4001 label, in the order they are read.
REAL_BARCODES = ["8944303353394670590", "07940732211", "335339467059", "SN:0442607280004"]
# What Windows OCR makes of the print on that same label.
REAL_PRINT = ("HZ-4001-4H-GT UKC< 4CH HDD cnr-c 11): 044270960004 WITH 4G "
              "SN : 0442607280004 SINN BT PLC, 1 Braham Street, London El BEE "
              "SIM No. 335339467059 Mobile No .07940732211")


def test_a_real_label_reads_completely():
    fields = classify(REAL_BARCODES, REAL_PRINT)
    assert fields["device_id"] == "044270960004"     # printed only, never barcoded
    assert fields["device_id_source"] == "text"
    assert fields["serial"] == "0442607280004"
    assert fields["mobile_no"] == "07940732211"
    assert fields["sim_no"] == "335339467059"
    assert fields["iccid"] == "8944303353394670590"


def test_the_iccid_is_not_mistaken_for_the_sim_number():
    """Both are barcoded, and the SIM number is a run of digits inside the ICCID."""
    fields = classify(REAL_BARCODES, REAL_PRINT)
    assert fields["sim_no"] == "335339467059"
    assert fields["sim_no"] != fields["iccid"]


def test_the_serial_is_not_read_as_the_device_id():
    """The serial is thirteen digits; its first twelve look exactly like an ID."""
    fields = classify(["SN:0442607280004"], "SN : 0442607280004")
    assert fields["device_id"] is None
    assert fields["serial"] == "0442607280004"


def test_two_possible_ids_are_refused_rather_than_guessed():
    """A wrong ID points the camera at nothing, so a guess is worse than none."""
    fields = classify([], "ID: 044270960004 and also 055270960007")
    assert fields["device_id"] is None


def test_each_number_is_recognised_by_its_shape():
    fields = classify(["0442607280004", "044270960004", "07940732211", "335339467059"])
    assert fields["device_id"] == "044270960004"     # 12 digits, leading zero
    assert fields["device_id_source"] == "barcode"
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

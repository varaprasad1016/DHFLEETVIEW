"""Reading a DVR's label from a photo of it.

What is on one of these labels, and where it comes from:

  ID:044270960004     the device ID - printed only, NOT barcoded. The barcode
                      sitting directly under it carries the serial number, so
                      this one has to be read off the print.
  SN:0442607280004    the serial, both printed and in that barcode.
  SIM No. 3353...     the SIM number CNMS wants, printed with its own barcode.
  Mobile No. 0794...  the number the setup texts are sent to, barcoded.
  a long 89... code   the SIM's ICCID, barcoded at the foot of the label. It is
                      not the SIM number, and the SIM number is a run of digits
                      inside it, so the two are easily confused.

The registration and the customer are handwritten, so they are always confirmed
by hand afterwards.
"""

from __future__ import annotations

import io
import logging
import re

from app.services import dvr_ocr

logger = logging.getLogger("tacho.labels")

# Device IDs on these units are twelve digits and start 044; the serial beneath
# them is thirteen. A UK mobile is eleven digits starting 07.
DEVICE_ID = re.compile(r"^0\d{11}$")
SERIAL = re.compile(r"^\d{13}$")
MOBILE = re.compile(r"^07\d{9}$")
ICCID = re.compile(r"^89\d{15,18}$")
SIM = re.compile(r"^\d{10,14}$")
PLATE = re.compile(r"^[A-Z]{2}\d{2}\s?[A-Z]{3}$")


def read_barcodes(data: bytes) -> list[str]:
    """Every barcode in the photo, in reading order, without duplicates.

    Phone photos are large and often slightly rotated; the image is scaled down
    for speed and retried a quarter-turn each way before giving up.
    """
    from PIL import Image, ImageOps
    from pyzbar import pyzbar

    image = Image.open(io.BytesIO(data))
    image = ImageOps.exif_transpose(image)
    if max(image.size) > 2000:
        scale = 2000 / max(image.size)
        image = image.resize((int(image.width * scale), int(image.height * scale)))
    grey = image.convert("L")

    seen: list[str] = []
    for candidate in (grey, grey.rotate(90, expand=True), grey.rotate(270, expand=True), ImageOps.autocontrast(grey)):
        for found in pyzbar.decode(candidate):
            try:
                value = found.data.decode("utf-8").strip()
            except UnicodeDecodeError:
                continue
            if value and value not in seen:
                seen.append(value)
        if len(seen) >= 3:
            break
    return seen


def classify(values: list[str], printed: str = "") -> dict:
    """Sort what was read off a label into the fields it belongs to.

    `values` are the barcodes; `printed` is the text read off the label, which
    is where the device ID has to come from.
    """
    fields: dict = {"device_id": None, "device_id_source": None, "serial": None, "sim_no": None,
                    "mobile_no": None, "iccid": None, "registration": None, "barcodes": values}
    for value in values:
        digits = re.sub(r"\D", "", value)
        plate = value.replace(" ", "").upper()
        if PLATE.match(plate) and not fields["registration"]:
            fields["registration"] = plate
        elif MOBILE.match(digits) and not fields["mobile_no"]:
            fields["mobile_no"] = digits
        elif SERIAL.match(digits) and not fields["serial"]:
            fields["serial"] = digits
        elif ICCID.match(digits) and not fields["iccid"]:
            fields["iccid"] = digits
        elif DEVICE_ID.match(digits) and not fields["device_id"]:
            fields["device_id"] = digits        # some labels do barcode the ID
            fields["device_id_source"] = "barcode"
        elif SIM.match(digits) and not fields["sim_no"]:
            fields["sim_no"] = digits

    if fields["device_id"] is None and printed:
        fields["device_id"] = _printed_device_id(printed, fields)
        if fields["device_id"]:
            fields["device_id_source"] = "text"

    # Nothing else carried the SIM number: fall back to the ICCID, which CNMS
    # will at least accept, rather than leaving the field empty.
    if not fields["sim_no"] and fields["iccid"]:
        fields["sim_no"] = fields["iccid"]
    return fields


def _printed_device_id(printed: str, fields: dict) -> str | None:
    """The device ID out of the label's printed text.

    It is twelve digits beginning with a zero. The SIM number is twelve digits
    too, so anything already claimed from a barcode is ruled out first, and an
    ID is only accepted if exactly one candidate is left - a misread digit here
    would point the camera at nothing, so a guess is worse than nothing.
    """
    claimed = {fields.get(name) for name in ("serial", "sim_no", "mobile_no", "iccid")}
    # A run of exactly twelve digits: without the guards this would also match
    # the first twelve digits of the thirteen-digit serial printed below it.
    candidates = {run for run in re.findall(r"(?<!\d)\d{12}(?!\d)", printed)
                  if DEVICE_ID.match(run) and run not in claimed}
    if len(candidates) == 1:
        return candidates.pop()
    if candidates:
        logger.warning("a label photo showed %d possible device IDs, so none was taken",
                       len(candidates))
    return None


def read_label(data: bytes) -> dict:
    """What the photo of a label says, as far as it can be read."""
    try:
        values = read_barcodes(data)
    except Exception:  # noqa: BLE001 - an unreadable photo is answered, not raised
        logger.exception("could not read barcodes from a label photo")
        values = []
    fields = classify(values, dvr_ocr.read_text(data))
    fields["read"] = bool(fields["device_id"])
    return fields

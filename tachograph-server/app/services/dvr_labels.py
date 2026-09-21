"""Reading a DVR's label from a photo of it.

Everything that matters on these labels is barcoded - the device ID, the SIM
number and the SIM's mobile number - so the numbers are read from the barcodes
rather than guessed from the picture. The registration and the customer are
handwritten on the label, so they are confirmed by hand afterwards.
"""

from __future__ import annotations

import io
import logging
import re

logger = logging.getLogger("tacho.labels")

# Device IDs on these units are twelve digits and start 044; the serial beneath
# them is thirteen. A UK mobile is eleven digits starting 07.
DEVICE_ID = re.compile(r"^0\d{11}$")
SERIAL = re.compile(r"^\d{13}$")
MOBILE = re.compile(r"^07\d{9}$")
SIM = re.compile(r"^\d{10,20}$")
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


def classify(values: list[str]) -> dict:
    """Sort the numbers read off a label into the fields they belong to."""
    fields: dict = {"device_id": None, "serial": None, "sim_no": None, "mobile_no": None,
                    "registration": None, "barcodes": values}
    for value in values:
        digits = re.sub(r"\D", "", value)
        plate = value.replace(" ", "").upper()
        if PLATE.match(plate) and not fields["registration"]:
            fields["registration"] = plate
        elif MOBILE.match(digits) and not fields["mobile_no"]:
            fields["mobile_no"] = digits
        elif SERIAL.match(digits) and not fields["serial"]:
            fields["serial"] = digits
        elif DEVICE_ID.match(digits) and not fields["device_id"]:
            fields["device_id"] = digits
        elif SIM.match(digits) and not fields["sim_no"]:
            fields["sim_no"] = digits
    # A label where the ID came through as the only long number: treat the
    # longest unclaimed value as the SIM rather than dropping it.
    if fields["device_id"] and not fields["sim_no"]:
        spare = [re.sub(r"\D", "", v) for v in values
                 if re.sub(r"\D", "", v) not in (fields["device_id"], fields["serial"], fields["mobile_no"])]
        fields["sim_no"] = next((s for s in spare if len(s) >= 10), None)
    return fields


def read_label(data: bytes) -> dict:
    """What the photo of a label says, as far as it can be read."""
    try:
        values = read_barcodes(data)
    except Exception:  # noqa: BLE001 - an unreadable photo is answered, not raised
        logger.exception("could not read barcodes from a label photo")
        values = []
    fields = classify(values)
    fields["read"] = bool(fields["device_id"])
    return fields

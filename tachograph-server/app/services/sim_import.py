"""Reading a SIM list exported from the provider's portal.

Their API answers about one SIM at a time and cannot list an account's SIMs, so
the stock comes from a CSV export. The column names in such exports vary and
change between versions, so nothing here depends on an exact heading: each
column is recognised by what its heading resembles, and an ICCID is recognised
by its own shape as a last resort.

Anything it cannot place is reported back rather than dropped, so an export in
an unexpected shape is obvious immediately instead of silently importing half
of itself.
"""

from __future__ import annotations

import csv
import io
import logging
import re

logger = logging.getLogger("tacho.sims")

# A heading counts as a field if it contains one of these, once punctuation and
# spacing are taken out. Longest first, so "sim number" is not read as "number".
HEADINGS = {
    "iccid": ("iccid", "simserial", "serialnumber", "simcardnumber", "simid"),
    "msisdn": ("simphonenumber", "msisdn", "mobilenumber", "phonenumber", "mobile",
               "number", "telno"),
    "sim_no": ("simno", "simnumber", "subscribernumber"),
    "status": ("simstatus", "status", "state"),
    "group": ("group", "tariff", "plan", "billinggroup"),
    "network": ("simtype", "network", "operator", "carrier", "provider"),
    # Which unit the SIM is actually in, as the network sees it. Worth having:
    # it is how a SIM in stock can be told apart from one already in a camera.
    "imei": ("imei",),
    "data_mb": ("databalance", "datausage", "datamb", "mtddata"),
}
ICCID = re.compile(r"^89\d{16,18}$")
UK_MOBILE = re.compile(r"^(?:44|0)7\d{9}$")


def _flatten(heading: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (heading or "").lower())


def map_columns(headings: list[str]) -> dict[str, int]:
    """Which column holds which field, by what each heading resembles."""
    found: dict[str, int] = {}
    for index, heading in enumerate(headings):
        flat = _flatten(heading)
        if not flat:
            continue
        for field, hints in HEADINGS.items():
            if field in found:
                continue
            if any(hint in flat for hint in hints):
                found[field] = index
                break
    return found


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _tidy_number(value: str) -> str | None:
    """A mobile number as we store it: 07... for a UK one, digits otherwise."""
    digits = _digits(value)
    if not digits:
        return None
    if digits.startswith("447") and len(digits) == 12:
        return "0" + digits[2:]
    if digits.startswith("00"):
        digits = digits[2:]
        if digits.startswith("447") and len(digits) == 12:
            return "0" + digits[2:]
    return digits


def _rows_from_spreadsheet(data: bytes) -> list[list[str]]:
    """The first sheet of an .xlsx, as text.

    The portal's own export is a spreadsheet, not a CSV, so this is the usual
    case rather than the exception. Dates and numbers come back as values, so
    they are turned into plain strings here and read like any other cell.
    """
    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]
    rows = []
    for row in sheet.iter_rows(values_only=True):
        rows.append(["" if cell is None else str(cell) for cell in row])
    workbook.close()
    return rows


def read(data: bytes) -> dict:
    """Every SIM in an exported list, and anything that could not be read.

    Takes the portal's .xlsx export or a CSV saved from it.
    Returns {"sims": [...], "skipped": [...], "columns": {...}}.
    """
    if data[:2] == b"PK":            # a zip, so an .xlsx
        try:
            return _from_rows(_rows_from_spreadsheet(data))
        except Exception as exc:  # noqa: BLE001
            logger.exception("a SIM export could not be read as a spreadsheet")
            raise ValueError(f"That spreadsheet could not be read: {exc}") from exc

    text = data.decode("utf-8-sig", errors="replace")
    # Exports come out comma, semicolon or tab separated depending on locale.
    try:
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return _from_rows(list(csv.reader(io.StringIO(text), dialect)))


def _from_rows(rows: list[list[str]]) -> dict:
    """Sort rows of a table into SIMs, however the table arrived."""
    if not rows:
        return {"sims": [], "skipped": [], "columns": {}}

    columns = map_columns(rows[0])
    body = rows[1:] if columns else rows
    if not columns:
        logger.info("a SIM export arrived with no headings it recognised")

    sims, skipped = [], []
    for number, row in enumerate(body, start=2 if columns else 1):
        if not any(cell.strip() for cell in row):
            continue

        def cell(field: str) -> str:
            index = columns.get(field)
            return row[index].strip() if index is not None and index < len(row) else ""

        iccid = _digits(cell("iccid"))
        if not ICCID.match(iccid):
            # No usable heading, or a heading that was not the ICCID: fall back
            # to finding something ICCID-shaped anywhere in the row.
            iccid = next((_digits(c) for c in row if ICCID.match(_digits(c))), "")
        if not iccid:
            skipped.append({"row": number, "why": "no ICCID in this row",
                            "content": ",".join(row)[:120]})
            continue

        msisdn = _tidy_number(cell("msisdn"))
        if not msisdn:
            msisdn = next((_tidy_number(c) for c in row
                           if UK_MOBILE.match(_digits(c))), None)

        try:
            data_mb = float(cell("data_mb")) if cell("data_mb") else None
        except ValueError:
            data_mb = None

        sims.append({
            "iccid": iccid,
            "msisdn": msisdn,
            "sim_no": cell("sim_no") or None,
            "status": cell("status") or None,
            "group": (cell("group") or "").strip() or None,
            "network": cell("network") or None,
            "imei": _digits(cell("imei")) or None,
            "data_mb": data_mb,
        })

    return {"sims": sims, "skipped": skipped,
            "columns": {field: rows[0][index] for field, index in columns.items()
                        if index < len(rows[0])}}

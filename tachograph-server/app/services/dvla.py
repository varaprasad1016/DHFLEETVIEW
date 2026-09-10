"""DVLA Vehicle Enquiry Service (VES) client.

Looks up a UK registration for tax status/expiry, MOT status/expiry, and the
emissions data (fuel type, CO2, Euro status). Free API; needs a key from
register-for-ves.driver-vehicle-licensing.api.gov.uk in settings.dvla_ves_api_key.

Uses stdlib urllib in a worker thread so it never blocks the async loop and adds
no dependency.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from datetime import date, datetime

from app.config import settings


class DvlaError(Exception):
    pass


class DvlaNotConfigured(DvlaError):
    pass


def configured() -> bool:
    return bool(settings.dvla_ves_api_key)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _lookup_sync(reg: str) -> dict:
    body = json.dumps({"registrationNumber": reg}).encode()
    req = urllib.request.Request(
        settings.dvla_ves_url, data=body, method="POST",
        headers={"x-api-key": settings.dvla_ves_api_key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            payload = json.loads(e.read() or b"{}")
        except ValueError:
            payload = {}
        if code == 404:
            raise DvlaError("Vehicle not found at DVLA.")
        if code in (401, 403):
            raise DvlaError("DVLA rejected the API key (check it is live).")
        if code == 429:
            raise DvlaError("DVLA rate limit hit; try again shortly.")
        msg = ""
        if isinstance(payload, dict) and payload.get("errors"):
            msg = payload["errors"][0].get("detail") or payload["errors"][0].get("title") or ""
        raise DvlaError(f"DVLA error {code}: {msg}" if msg else f"DVLA error {code}.")
    except urllib.error.URLError as e:
        raise DvlaError(f"Cannot reach DVLA: {e.reason}")


async def lookup(reg: str) -> dict:
    """Return normalised fields for one registration."""
    if not configured():
        raise DvlaNotConfigured("DVLA VES API key is not set.")
    raw = await asyncio.to_thread(_lookup_sync, reg)
    return {
        "make": raw.get("make"),
        "colour": raw.get("colour"),
        "year": raw.get("yearOfManufacture"),
        "fuel_type": raw.get("fuelType"),
        "co2": raw.get("co2Emissions"),
        "euro_status": raw.get("euroStatus"),
        "engine_capacity": raw.get("engineCapacity"),
        "tax_status": raw.get("taxStatus"),
        "tax_due_date": _parse_date(raw.get("taxDueDate")),
        "mot_status": raw.get("motStatus"),
        "mot_expiry_date": _parse_date(raw.get("motExpiryDate")),
        "marked_for_export": raw.get("markedForExport"),
    }

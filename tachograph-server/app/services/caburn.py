"""Talking to Caburn's SIM Insight API.

Every operation is the same document: the operation element, an authentication
block, and the SIM it concerns. Only the fields differ. So there is one call
here and the operations are a line each, rather than five near-identical
functions.

Two things about this API shape the code:

  * it answers HTTP 200 whether or not the operation worked, putting the real
    result in <api-outcome>. Believing the status code would report failures as
    successes, so the outcome is what is believed;
  * five wrong passwords lock the account, and a locked account needs a phone
    call to Caburn to unlock. Nothing here retries a refused login.

A SIM is addressed by ICCID where we know it, since that never changes, and by
number otherwise - both are accepted.
"""

from __future__ import annotations

import logging
import re
from xml.sax.saxutils import escape

import httpx

from app.config import settings

logger = logging.getLogger("tacho.caburn")

QUOTES = {'"': "&quot;", "'": "&#39;"}
TIMEOUT = 30


class CaburnError(Exception):
    """The API refused an operation, in its own words."""


def configured() -> bool:
    return bool(settings.sms_url and settings.sms_username and settings.sms_password)


def international(number: str) -> str:
    """A UK mobile as their API wants it: 07940732131 -> 447940732131."""
    digits = re.sub(r"\D", "", number or "")
    if digits.startswith("07"):
        return "44" + digits[1:]
    if digits.startswith("00"):
        return digits[2:]
    return digits


def _target(iccid: str | None, msisdn: str | None) -> str:
    """How the SIM is named in the request."""
    if iccid:
        return f"<iccid>{escape(str(iccid), QUOTES)}</iccid>"
    if msisdn:
        return f"<msisdn>{international(msisdn)}</msisdn>"
    raise CaburnError("No SIM was given: an ICCID or a mobile number is needed.")


def build(operation: str, iccid: str | None = None, msisdn: str | None = None,
          **fields: str) -> str:
    """One API document, with the reserved XML characters escaped."""
    extra = "".join(f"<{name}>{escape(str(value), QUOTES)}</{name}>"
                    for name, value in fields.items() if value not in (None, ""))
    return (
        f'<{operation} version="1">'
        f"<authentication><username>{escape(settings.sms_username, QUOTES)}</username>"
        f"<password>{escape(settings.sms_password, QUOTES)}</password></authentication>"
        f"{_target(iccid, msisdn)}{extra}"
        f"</{operation}>"
    )


def read(body: str, name: str) -> str | None:
    """One element out of a response, if it is there."""
    found = re.search(rf"<{name}>\s*(.*?)\s*</{name}>", body, re.I | re.S)
    return found.group(1) if found else None


async def call(client: httpx.AsyncClient, operation: str, iccid: str | None = None,
               msisdn: str | None = None, **fields: str) -> str:
    """Run one operation and hand back the response body.

    Raises CaburnError with the API's own wording if it refused, so "SIM not
    active" or "Rejected by operator" reaches the screen intact.
    """
    if not configured():
        raise CaburnError("The SIM portal is not set up on this server.")

    try:
        response = await client.post(settings.sms_url,
                                     headers={"Content-Type": "text/xml; charset=utf-8"},
                                     content=build(operation, iccid, msisdn, **fields).encode("utf-8"),
                                     timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise CaburnError(f"The SIM portal could not be reached: {exc}") from exc

    if response.status_code >= 300:
        raise CaburnError(f"The SIM portal refused it ({response.status_code}): "
                          f"{response.text.strip()[:200]}")

    outcome = read(response.text, "api-outcome") or ""
    if outcome.lower() != "success":
        raise CaburnError(outcome or f"The SIM portal gave no outcome: {response.text.strip()[:200]}")
    return response.text


# --------------------------------------------------------------- operations
async def send_sms(client: httpx.AsyncClient, *, text: str, iccid: str | None = None,
                   msisdn: str | None = None, reference: str = "") -> str:
    """A text message to the SIM in a camera."""
    if len(text) > 160:
        raise CaburnError(f"That message is {len(text)} characters; the limit is 160.")
    await call(client, "send-sms", iccid, msisdn, **{"message-text": text,
                                                     "sms-uid": reference[:12]})
    return f"accepted by the SIM portal{f' (ref {reference[:12]})' if reference else ''}"


async def status(client: httpx.AsyncClient, *, iccid: str | None = None,
                 msisdn: str | None = None) -> str:
    """Active, Deactivated or Closed.

    Active is necessary but not sufficient: their documentation notes a SIM
    must also be in a live group before it will carry traffic.
    """
    return read(await call(client, "query-status", iccid, msisdn), "status") or "Unknown"


async def usage(client: httpx.AsyncClient, *, iccid: str | None = None,
                msisdn: str | None = None) -> dict:
    """Data, SMS and voice used so far this calendar month."""
    body = await call(client, "query-usage", iccid, msisdn)
    return {"data_mb": _float(read(body, "data-mb")),
            "sms": _int(read(body, "sms")),
            "voice_mins": _int(read(body, "voice-mins"))}


async def msisdn_of(client: httpx.AsyncClient, iccid: str) -> str | None:
    """The number a SIM answers on, which can change where the ICCID cannot."""
    return read(await call(client, "query-msisdn", iccid), "msisdn")


# The only data levels their API accepts, in MB. Anything else is refused as
# "Invalid Content", so a level is always rounded onto this ladder.
USAGE_STEPS = (1, 1.5, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 70, 80,
               100, 120, 150, 200, 250, 300, 400, 500, 600, 700, 800, 1024, 1536, 2048,
               2560, 3072, 4096, 5120, 6144, 7168, 8192, 10240, 15360, 20480, 30720,
               40960, 51200, 61440, 71680, 81920, 102400, 153600, 204800, 256000,
               409600, 512000, 819200, 1048576, 2097152, 5242880)


def step_at_least(value: float) -> float:
    """The smallest level their API accepts that is not below this."""
    return next((step for step in USAGE_STEPS if step >= value), USAGE_STEPS[-1])


def next_step_above(value: float) -> float:
    """The next level up from where a SIM is now."""
    return next((step for step in USAGE_STEPS if step > value), USAGE_STEPS[-1])


def tidy_level(value: float) -> float:
    """A level as their API wants it: whole MB, except the 1.5 MB step."""
    step = step_at_least(float(value))
    return step if step == 1.5 else int(step)


async def set_usage_levels(client: httpx.AsyncClient, *, iccid: str,
                           warning: float | None = None,
                           limit: float | None = None) -> dict:
    """Set the data levels at which a SIM warns, and at which it is cut off.

    Reaching the limit disables the SIM's traffic - which is how a camera goes
    dark mid-month - so raising it is what "topping up" means for these SIMs.
    Levels are in MB and must land on their ladder of allowed values, so both
    are rounded up onto it rather than refused.

    Only works for SIMs in a live group, and never for pre-paid ones; their API
    answers "Invalid ICCID" otherwise.
    """
    if warning is None and limit is None:
        raise CaburnError("Nothing to set: give a warning level, a limit, or both.")
    fields = {}
    if warning is not None:
        fields["warning"] = str(tidy_level(warning))
    if limit is not None:
        fields["limit"] = str(tidy_level(limit))
    # Their rule: a limit below the warning silently drags both down to the
    # warning, so it is worth not sending that by accident.
    if warning is not None and limit is not None and float(fields["limit"]) < float(fields["warning"]):
        raise CaburnError("The cut-off cannot be lower than the warning level.")

    await call(client, "set-usage-levels", iccid, **fields)
    logger.info("set SIM %s usage levels to %s", iccid, fields)
    return {k: float(v) for k, v in fields.items()}


async def set_status(client: httpx.AsyncClient, *, active: bool, iccid: str | None = None,
                     msisdn: str | None = None) -> str:
    """Turn a SIM on or off.

    This stops or allows all traffic on the SIM, so a camera whose SIM is
    deactivated goes dark. It does not change the tariff group, so it does not
    change what the SIM costs.
    """
    wanted = "active" if active else "de-activated"
    await call(client, "set-status", iccid, msisdn, status=wanted)
    logger.info("set SIM %s to %s", iccid or msisdn, wanted)
    return wanted


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _int(value: str | None) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except ValueError:
        return None

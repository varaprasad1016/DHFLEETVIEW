"""Reading the operating company off a vehicle unit, and keeping it straight.

The name arrives in a fixed field of the VU overview, preceded by a code-page
byte and whatever the neighbouring field left behind - "2\\x01AMTRAK LOGISTICS
LTD" in the files we hold. It has to be cleaned before it is worth storing, and
matched loosely enough that "A B Haulage Ltd" and "A B HAULAGE LIMITED" are one
company rather than two, while still keeping the name exactly as the
tachograph recorded it for the paperwork.

Two rules matter more than the parsing:

Nothing is invented. A file that yields no readable name attaches no operator,
rather than guessing from the account it was uploaded to.

Nothing is silently changed. A vehicle that has been sold on, or a unit whose
company card belongs to someone else, shows up as a disagreement for a person
to settle - because overwriting it would quietly re-badge every historical
report for that truck.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operator import Operator

logger = logging.getLogger("tacho.operators")

# Legal suffixes that are the same company written two ways.
_SUFFIXES = {
    "LIMITED": "LTD",
    "PUBLIC LIMITED COMPANY": "PLC",
    "COMPANY": "CO",
    "INCORPORATED": "INC",
}
_PUNCTUATION = re.compile(r"[^A-Z0-9 ]+")
_SPACES = re.compile(r"\s+")
# What a company name is actually made of. Anything else is a sign the field
# was not a name at all - most often a file read at the wrong offset, or one
# mistaken for a vehicle unit when it is a driver card.
_PLAUSIBLE = re.compile(r"[A-Za-z0-9 &.,'()/-]")
_MIN_PLAUSIBLE = 0.8
_MIN_LETTERS = 2


def clean_name(raw: str | None) -> str | None:
    """The operator's name as it should read, from the raw VU field.

    The field carries a code-page byte, and in practice a character or two of
    the field before it. Everything up to and including the last control
    character near the front is dropped, which removes both without having to
    guess at an offset that differs between vehicle-unit generations.
    """
    if not raw:
        return None
    text = raw.replace("\x00", " ")
    # Control characters only ever appear as framing, never inside a name.
    lead = [i for i, ch in enumerate(text[:8]) if ord(ch) < 0x20]
    if lead:
        text = text[lead[-1] + 1:]
    # Anything non-printable further in is framing too, so stop at it.
    text = "".join(ch for ch in text if ch.isprintable())
    text = _SPACES.sub(" ", text).strip(" .,-")
    if not text:
        return None

    # The field is raw bytes at a fixed offset, so a file read at the wrong
    # place - or a driver card mistaken for a vehicle unit - lands arbitrary
    # binary here. Some of it survives cleaning and still contains letters, so
    # "has a letter in it" is not enough: a name has to look like a name, or a
    # customer ends up with mojibake printed on their report.
    if sum(1 for ch in text if _PLAUSIBLE.match(ch)) < len(text) * _MIN_PLAUSIBLE:
        logger.warning("ignoring an operator name that does not read like one: %r",
                       text[:40])
        return None
    if sum(1 for ch in text if ch.isalpha()) < _MIN_LETTERS:
        return None
    return text[:160]


def match_key(name: str) -> str:
    """The comparable form of a name, for recognising one company twice.

    Deliberately conservative: case, punctuation, spacing and the usual legal
    suffixes are normalised, and nothing else. Two genuinely different
    companies must never collapse into one, which would put one operator's
    drivers on another's report.
    """
    key = _PUNCTUATION.sub(" ", name.upper())
    key = _SPACES.sub(" ", key).strip()
    for long_form, short in _SUFFIXES.items():
        key = re.sub(rf"\b{long_form}\b", short, key)
    return _SPACES.sub(" ", key).strip()[:160]


async def resolve(session: AsyncSession, raw: str | None, *,
                  source: str = "download") -> Operator | None:
    """The operator this name refers to, creating the record the first time.

    Returns None when there is no readable name, which is the honest answer for
    a file whose overview we could not read: better no operator than the wrong
    one.
    """
    name = clean_name(raw)
    if name is None:
        return None
    key = match_key(name)
    if not key:
        return None

    found = (await session.execute(
        select(Operator).where(Operator.match_key == key))).scalar_one_or_none()
    if found is not None:
        return found

    operator = Operator(name=name, match_key=key, source=source)
    session.add(operator)
    await session.flush()
    logger.info("new operating company from a %s: %s", source, name)
    return operator


async def note_vehicle(vehicle, operator: Operator | None) -> str:
    """Record which company operates a vehicle. Returns what happened.

    set        the vehicle had no operator and now has one
    unchanged  it already belonged to this operator
    conflict   the unit names a different company from the one on record
    none       there was nothing to record
    """
    if operator is None or vehicle is None:
        return "none"
    if vehicle.operator_id is None:
        vehicle.operator_id = operator.id
        return "set"
    if vehicle.operator_id == operator.id:
        return "unchanged"
    # Left as it was on purpose. A truck really can change hands, but that is a
    # decision with history behind it - every past report for this vehicle
    # carries the old name - so it is put in front of a person instead.
    logger.warning("vehicle %s is recorded against another operator; the unit says %s",
                   getattr(vehicle, "registration", "?"), operator.name)
    return "conflict"

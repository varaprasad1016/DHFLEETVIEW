"""Download currency: which units and cards are overdue a download.

The first thing asked for at a DVSA visit is not whether the fleet is
compliant but whether it can prove it, and the proof is the download record.
These two reports answer that in the shape an operator is used to being asked:
one row per vehicle, one row per driver, worst first.

Two things this deliberately does differently from a plain listing of files:

  The fleet is the universe, not the archive. A vehicle that has never been
  downloaded is the most important row on the report, and it has no file to
  list it by. So the rows are built from the account's vehicles and drivers and
  the downloads are joined onto them - never the other way round.

  "Never" is red, not blank. A missing figure here reads as an absence of
  concern, when it is the opposite.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tacho import TachoActivity, TachoFile
from app.services.tacho_scope import TachoScope, card_key, primary_reg, reg_key

# The regulation sets the outer limit; the amber band is the operator's own
# early warning, placed so a unit about to breach appears on the report before
# it does rather than after.
#
#   vehicle unit   90 days by law (EU 165/2014 art. 33). Red at 57 because a
#                  single further missed cycle carries it past 90.
#   driver card    28 days by law. Red at 29 - already late, not nearly late.
VU_BANDS = (14, 56)
CARD_BANDS = (14, 28)


def _name_key(value: str | None) -> str:
    """Driver names compare on letters and digits alone.

    Not `card_key`, which truncates to the 14 characters a card number is -
    on a name that silently merges two drivers whose first fourteen letters
    agree, which is exactly the kind of fault that shows up only once a real
    fleet is loaded.
    """
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _band(days: int | None, bands: tuple[int, int]) -> str:
    if days is None:
        return "red"
    green, amber = bands
    return "green" if days <= green else ("amber" if days <= amber else "red")


def _days(when: datetime | None, today: date) -> int | None:
    if when is None:
        return None
    return (today - when.astimezone(timezone.utc).date()).days


def _depot(record: dict, fallback: str | None) -> str:
    """Depot, where an operator keeps one.

    Nothing in the tachograph data names a depot - it is an organisational
    fact, not a recorded one - so it is read from the vehicle's or driver's
    own attributes and falls back to the operator name. A single-site operator
    then gets a correct column without having to model a depot at all.
    """
    attrs = record.get("attributes") or {}
    return (attrs.get("depot") or attrs.get("tachoDepot") or fallback or "").strip()


async def _latest_files(session: AsyncSession, scope: TachoScope, kind: str,
                        column) -> dict[str, datetime]:
    rows = (await session.execute(
        select(column, func.max(TachoFile.created_at))
        .where(scope.files(), TachoFile.file_kind == kind, column.is_not(None))
        .group_by(column))).all()
    out: dict[str, datetime] = {}
    for key, when in rows:
        norm = reg_key(key) if kind == "vehicle_unit" else card_key(key)
        if norm and (norm not in out or (when and when > out[norm])):
            out[norm] = when
    return out


def _archive_fleet(latest: dict[str, datetime]) -> list[dict]:
    """Stand-in vehicle list for a scope that has no fleet of its own.

    An administrator looking at everything has no Traccar device list to build
    rows from, and returning nothing there would read as "all downloads are
    current" - the one answer this report must never give by accident. So the
    archive itself becomes the universe. It cannot show a vehicle that has
    never been downloaded, which is exactly why it is the fallback and not the
    primary path.
    """
    return [{"name": reg, "attributes": {}} for reg in sorted(latest)]


async def vu_submission(session: AsyncSession, scope: TachoScope,
                        today: date | None = None,
                        operator_name: str | None = None) -> list[dict]:
    """One row per vehicle: how long since its unit was last downloaded."""
    today = today or datetime.now(timezone.utc).date()
    latest = await _latest_files(session, scope, "vehicle_unit", TachoFile.vehicle_ref)

    fleet = scope.devices or _archive_fleet(latest)
    rows = []
    for device in fleet:
        reg = primary_reg(device)
        if not reg:
            continue
        key = reg_key(reg)
        when = latest.get(key)
        days = _days(when, today)
        attrs = device.get("attributes") or {}
        rows.append({
            "registration": reg,
            # Fleet facts the tachograph never records. Shown when the operator
            # has set them, left blank rather than guessed when not.
            "asset": attrs.get("ownership") or "Owned",
            "type": attrs.get("bodyType") or attrs.get("vehicleType") or "",
            "status": "Inactive" if device.get("disabled") else "Active",
            "situation": attrs.get("situation") or "Running",
            "depot": _depot(device, operator_name),
            "last_download": when.astimezone(timezone.utc).date().isoformat() if when else None,
            "days_since_download": days,
            "band": _band(days, VU_BANDS),
        })

    # Worst first: never-downloaded at the top, then oldest. That ordering is
    # the point of the report - the rows that need acting on are the ones you
    # should not have to scroll to.
    rows.sort(key=lambda r: (-1 if r["days_since_download"] is None else -r["days_since_download"],
                             r["registration"]))
    return rows


async def card_submission(session: AsyncSession, scope: TachoScope,
                          today: date | None = None,
                          operator_name: str | None = None) -> list[dict]:
    """One row per driver: last card download, and last activity on it.

    Both figures are carried because they answer different questions. A long
    gap since the last download is a process failure. A long gap since the last
    activity, with a recent download, is simply a driver who has not worked -
    and reading the first as the second is how a fleet ends up chasing a card
    that has nothing on it.
    """
    today = today or datetime.now(timezone.utc).date()
    latest = await _latest_files(session, scope, "driver_card", TachoFile.card_number)

    # Activities carry the driver's *name*, not their card number, so a card
    # cannot be matched to its activity directly. The file is the exact link -
    # every activity read out of a card file points back at it - and the name
    # is the fallback that catches work recorded by a vehicle unit, where there
    # is no card file to point at.
    files = (await session.execute(
        select(TachoFile.id, TachoFile.card_number, TachoFile.driver_ref)
        .where(scope.files(), TachoFile.file_kind == "driver_card",
               TachoFile.card_number.is_not(None)))).all()
    file_card: dict[uuid.UUID, str] = {}
    card_names: dict[str, set[str]] = {}
    for fid, card, name in files:
        key = card_key(card)
        if not key:
            continue
        file_card[fid] = key
        if name:
            card_names.setdefault(key, set()).add(_name_key(name))

    by_card: dict[str, datetime] = {}

    def _note(key: str | None, when: datetime | None) -> None:
        if key and when and (key not in by_card or when > by_card[key]):
            by_card[key] = when

    for fid, when in (await session.execute(
            select(TachoActivity.source_file_id, func.max(TachoActivity.ended_at))
            .where(scope.activities(), TachoActivity.source_file_id.in_(list(file_card) or [None]))
            .group_by(TachoActivity.source_file_id))).all():
        _note(file_card.get(fid), when)

    by_name: dict[str, datetime] = {}
    for ref, when in (await session.execute(
            select(TachoActivity.driver_ref, func.max(TachoActivity.ended_at))
            .where(scope.activities(), TachoActivity.driver_ref.is_not(None))
            .group_by(TachoActivity.driver_ref))).all():
        key = _name_key(ref)
        if key and when and (key not in by_name or when > by_name[key]):
            by_name[key] = when
    for key, names in card_names.items():
        for name in names:
            _note(key, by_name.get(name))
    activity = by_card

    roster = scope.drivers
    if not roster:
        # Same fallback as the vehicle report, with the name taken off the card
        # file so the rows are readable rather than a list of card numbers.
        names = {card_key(c): d for _, c, d in files if d}
        roster = [{"name": names.get(key, ""), "uniqueId": key, "attributes": {}}
                  for key in sorted(latest)]
    rows = []
    for driver in roster:
        card = str(driver.get("uniqueId") or "")
        key = card_key(card)
        if not key:
            continue
        when = latest.get(key)
        days = _days(when, today)
        attrs = driver.get("attributes") or {}
        # The account's own name for the driver is a third way in, and the only
        # one that works for a driver who has worked but whose card has never
        # been downloaded - the row this report exists to surface.
        last_act = activity.get(key) or by_name.get(_name_key(driver.get("name")))
        rows.append({
            "name": driver.get("name") or "",
            "card_number": card,
            "status": "Active",
            "type": attrs.get("driverType") or "Employed",
            "situation": attrs.get("situation") or "Working",
            "home_depot": _depot(driver, operator_name),
            "last_activity": last_act.astimezone(timezone.utc).date().isoformat() if last_act else None,
            "days_since_activity": _days(last_act, today),
            "last_download": when.astimezone(timezone.utc).date().isoformat() if when else None,
            "days_since_download": days,
            "band": _band(days, CARD_BANDS),
        })

    rows.sort(key=lambda r: (-1 if r["days_since_download"] is None else -r["days_since_download"],
                             r["name"]))
    return rows


def summarise(rows: list[dict]) -> dict:
    """Counts per band, for the page header and the email subject line."""
    out = {"green": 0, "amber": 0, "red": 0, "total": len(rows)}
    for row in rows:
        out[row["band"]] = out.get(row["band"], 0) + 1
    return out

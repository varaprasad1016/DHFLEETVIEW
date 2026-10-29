"""Driver performance: infringements scored, banded into levels, tracked to close.

An infringement engine answers "what went wrong". An operator running a
disciplinary process needs the next question answered - "who is this becoming a
pattern for, and what is still outstanding?" - and that is a policy layer, not
a parsing one. Nothing here is read out of a DDD file: the points, the bands
and the level-down period are the operator's own rules, and two operators
running the same fleet data will properly reach different levels.

So the scheme is data, not logic. The defaults below are a reasonable UK
operator's policy and are the right starting point for a fleet that has no
written scheme; a fleet that has one sets its own and these stop applying.

Item states, which are what the summary actually counts:

  open        raised, never put to the driver
  accepted    the office has debriefed it; the driver has not signed yet
  disputed    the driver contests it
  closed      debriefed and signed - the loop is complete

Outstanding is everything that is not closed. An accepted item is still
outstanding because the signature is the evidence, and an operator who cannot
produce it has no defence at a public inquiry.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.infringement_review import InfringementReview
from app.models.tacho import Infringement
from app.services.tacho_scope import TachoScope

# Annex I of the enforcement directive grades infringements; these weights
# follow that grading rather than inventing a parallel one.
DEFAULT_POINTS = {"minor": 1, "serious": 3, "very_serious": 5}

# Band -> the lowest score that reaches it. Read as "43 points or more is
# level 5". Open-ended at the top on purpose: there is no score at which a
# driver stops accruing.
DEFAULT_LEVELS = ((1, 1), (2, 6), (3, 17), (4, 31), (5, 43))

# An infringement older than this stops counting towards the current level. A
# driver who had a bad month two years ago is not a level 5 driver today.
DEFAULT_WINDOW_DAYS = 365

# Clean for this long and the driver comes down one level. This is the
# incentive half of the scheme, and leaving it out makes the level a record of
# the worst the driver has ever been rather than where they are now.
DEFAULT_LEVEL_DOWN_DAYS = 182

# Debriefed as nobody's fault: closed, and carrying no points. Scoring these
# would punish a driver for a traffic jam.
NO_FAULT = "not_driver_fault"
DISPUTED = "disputed"


@dataclass(frozen=True)
class Scheme:
    points: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_POINTS))
    levels: tuple[tuple[int, int], ...] = DEFAULT_LEVELS
    window_days: int = DEFAULT_WINDOW_DAYS
    level_down_days: int = DEFAULT_LEVEL_DOWN_DAYS

    def score(self, severity: str | None) -> int:
        return self.points.get((severity or "serious").lower(), 0)

    def level(self, points: int) -> int:
        band = 0
        for level, threshold in self.levels:
            if points >= threshold:
                band = level
        return band


def _state(review: InfringementReview | None) -> str:
    if review is None or not review.debrief_action:
        return "open"
    if review.debrief_action == DISPUTED:
        return "disputed"
    return "closed" if review.driver_signed_at is not None else "accepted"


async def summary(session: AsyncSession, scope: TachoScope,
                  today: date | None = None,
                  scheme: Scheme | None = None,
                  outstanding_only: bool = True,
                  operator_name: str | None = None) -> list[dict]:
    """One row per driver: level, points, and what is still outstanding."""
    scheme = scheme or Scheme()
    today = today or datetime.now(timezone.utc).date()
    window_start = today - timedelta(days=scheme.window_days)

    rows = (await session.execute(
        select(Infringement).where(scope.infringements(),
                                   Infringement.status != "dismissed"))).scalars().all()
    if not rows:
        return []

    reviews = (await session.execute(
        select(InfringementReview).where(
            InfringementReview.infringement_id.in_([r.id for r in rows])))).scalars().all()
    by_inf: dict[uuid.UUID, InfringementReview] = {r.infringement_id: r for r in reviews}

    drivers: dict[str, dict] = {}
    for inf in rows:
        ref = inf.driver_ref or ""
        d = drivers.setdefault(ref, {
            "driver_ref": ref, "depot": operator_name or "", "points": 0,
            "total_items": 0, "items_open": 0, "items_accepted": 0,
            "items_disputed": 0, "items_closed": 0,
            "_outstanding_dates": [], "_debriefs": [], "_latest": None,
        })
        review = by_inf.get(inf.id)
        state = _state(review)
        when = inf.period_start.astimezone(timezone.utc).date()

        d["total_items"] += 1
        d["items_" + state] += 1
        if d["_latest"] is None or when > d["_latest"]:
            d["_latest"] = when
        if review is not None and review.debriefed_at is not None:
            d["_debriefs"].append(review.debriefed_at.astimezone(timezone.utc).date())
        if state != "closed":
            d["_outstanding_dates"].append(when)
        # Points are the current picture, so they count only what is inside the
        # window and only what the driver was actually held responsible for.
        if when >= window_start and (review is None or review.debrief_action != NO_FAULT):
            d["points"] += scheme.score(inf.severity)

    out = []
    for d in drivers.values():
        outstanding = d["items_open"] + d["items_accepted"] + d["items_disputed"]
        if outstanding_only and not outstanding:
            continue
        level = scheme.level(d["points"])
        # Clean since the last infringement for the full period: one level back.
        clean_days = (today - d["_latest"]).days if d["_latest"] else None
        level_down = bool(level > 1 and clean_days is not None
                          and clean_days >= scheme.level_down_days)
        dates = sorted(d["_outstanding_dates"])
        out.append({
            "depot": d["depot"],
            "driver_ref": d["driver_ref"],
            "situation": "Working",
            "driver_type": "Employed",
            "level": max(1, level - 1) if level_down else level,
            "points": d["points"],
            "level_down_applied": level_down,
            "total_items": d["total_items"],
            "items_outstanding": outstanding,
            "items_open": d["items_open"],
            "items_accepted": d["items_accepted"],
            "items_disputed": d["items_disputed"],
            "items_closed": d["items_closed"],
            "last_debriefed_on": max(d["_debriefs"]).isoformat() if d["_debriefs"] else None,
            "earliest_outstanding": dates[0].isoformat() if dates else None,
            "latest_outstanding": dates[-1].isoformat() if dates else None,
            "days_since_last_item": clean_days,
        })

    # Worst first, by level then points - the order the transport manager wants
    # to work down, rather than alphabetical.
    out.sort(key=lambda r: (-r["level"], -r["points"], r["driver_ref"]))
    return out

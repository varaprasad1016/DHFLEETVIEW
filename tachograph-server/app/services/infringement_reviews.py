"""Helpers for infringement sign-off (driver) and debrief (office)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.infringement_review import InfringementReview

# Office debrief outcomes, in the order they're offered.
ACTIONS: dict[str, str] = {
    "explained": "Explained to the driver",
    "retraining": "Retraining arranged",
    "verbal_warning": "Verbal warning",
    "written_warning": "Written warning",
    "disciplinary": "Disciplinary action",
    "not_driver_fault": "Not the driver's fault (e.g. traffic, breakdown)",
    "disputed": "Driver disputes it — under review",
}


async def reviews_for(session: AsyncSession, infringement_ids) -> dict[uuid.UUID, InfringementReview]:
    ids = list(infringement_ids)
    if not ids:
        return {}
    rows = (await session.execute(
        select(InfringementReview).where(InfringementReview.infringement_id.in_(ids)))).scalars().all()
    return {r.infringement_id: r for r in rows}


def view(review: InfringementReview | None) -> dict:
    if review is None:
        return {"driver_signed_at": None, "driver_comment": None, "has_signature": False,
                "debriefed_at": None, "debriefed_by": None, "debrief_action": None,
                "debrief_action_label": None, "debrief_notes": None}
    return {
        "driver_signed_at": review.driver_signed_at.isoformat() if review.driver_signed_at else None,
        "driver_name": review.driver_name,
        "driver_comment": review.driver_comment,
        "has_signature": bool(review.driver_signature_path),
        "debriefed_at": review.debriefed_at.isoformat() if review.debriefed_at else None,
        "debriefed_by": review.debriefed_by,
        "debrief_action": review.debrief_action,
        "debrief_action_label": ACTIONS.get(review.debrief_action or ""),
        "debrief_notes": review.debrief_notes,
    }

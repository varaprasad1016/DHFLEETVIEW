"""A driver's sign-off and the office debrief for one infringement.

Operators have to show that drivers were told about their infringements and what
was done about them: the driver signs in the driver app, the office records the
debrief (explained, retraining, warning...).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InfringementReview(Base):
    __tablename__ = "infringement_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    infringement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("infringements.id", ondelete="CASCADE"), unique=True, nullable=False)
    driver_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("driver_accounts.id", ondelete="SET NULL"))
    driver_name: Mapped[str | None] = mapped_column(String(120))
    driver_signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    driver_signature_path: Mapped[str | None] = mapped_column(String(500))
    driver_comment: Mapped[str | None] = mapped_column(Text)
    debriefed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    debriefed_by: Mapped[str | None] = mapped_column(String(120))
    debrief_action: Mapped[str | None] = mapped_column(String(40))
    debrief_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

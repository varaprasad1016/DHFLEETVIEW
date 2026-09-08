"""Driver daily walkaround checks and defect reporting (DVSA "Guide to
maintaining roadworthiness").

A driver records a first-use walkaround before taking the vehicle out. Any
failed item raises a defect; dangerous/major defects mean the vehicle should be
taken off the road until rectified. Managers work the open-defect list and mark
each defect rectified, giving the audit trail an O-licence / Earned Recognition
review expects.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WalkaroundCheck(Base):
    __tablename__ = "walkaround_checks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    vehicle_reg: Mapped[str] = mapped_column(String(20), nullable=False)
    driver_name: Mapped[str | None] = mapped_column(String(100))
    check_type: Mapped[str] = mapped_column(String(10), server_default=text("'hgv'"))  # hgv|psv|van|car
    odometer_km: Mapped[int | None] = mapped_column(Integer)
    location: Mapped[str | None] = mapped_column(String(200))
    # 'pass' when every item is ok; 'defects' when one or more items failed.
    result: Mapped[str] = mapped_column(String(10), server_default=text("'pass'"))
    # Whether the driver declared the vehicle safe to drive despite any minor defects.
    safe_to_drive: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    defects: Mapped[list["WalkaroundDefect"]] = relationship(
        back_populates="check", cascade="all, delete-orphan")


class WalkaroundDefect(Base):
    __tablename__ = "walkaround_defects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    check_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("walkaround_checks.id", ondelete="CASCADE"), nullable=False)
    vehicle_reg: Mapped[str] = mapped_column(String(20), nullable=False)
    item: Mapped[str] = mapped_column(String(80), nullable=False)          # which walkaround item
    severity: Mapped[str] = mapped_column(String(10), server_default=text("'major'"))  # dangerous|major|minor
    description: Mapped[str | None] = mapped_column(Text)
    photo_key: Mapped[str | None] = mapped_column(String(500))             # optional MinIO/data ref
    # open -> being fixed; rectified -> closed; monitoring -> acceptable to run.
    status: Mapped[str] = mapped_column(String(12), server_default=text("'open'"))
    reported_by: Mapped[str | None] = mapped_column(String(100))
    rectified_by: Mapped[str | None] = mapped_column(String(100))
    rectification_notes: Mapped[str | None] = mapped_column(Text)
    rectified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    check: Mapped["WalkaroundCheck"] = relationship(back_populates="defects")

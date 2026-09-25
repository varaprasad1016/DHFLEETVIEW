"""Tacho compliance models: archived download files and detected infringements.

`TachoFile` is a self-contained archive record (works from a manual upload with
no provisioned Device/Driver row). `Infringement` stores one drivers'-hours / WTD
breach found by the rules engine, so managers can work an infringement list.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TachoActivity(Base):
    """Canonical activity span used by the timeline and downstream analysis."""

    __tablename__ = "tacho_activities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tacho_files.id", ondelete="CASCADE"), nullable=False)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("drivers.id"))
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vehicles.id"))
    driver_ref: Mapped[str | None] = mapped_column(String(40))
    vehicle_ref: Mapped[str | None] = mapped_column(String(20))
    activity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(20), server_default=text("'TACHOGRAPH'"))
    confidence: Mapped[str] = mapped_column(String(16), server_default=text("'DIRECT'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TachoFile(Base):
    __tablename__ = "tacho_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vehicles.id"))
    source_device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"))
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    file_kind: Mapped[str] = mapped_column(String(16), server_default=text("'unknown'"))  # driver_card|vehicle_unit|unknown
    driver_ref: Mapped[str | None] = mapped_column(String(40))   # card number or name
    vehicle_ref: Mapped[str | None] = mapped_column(String(20))  # registration/VRM
    card_number: Mapped[str | None] = mapped_column(String(32))  # driver card files: lets the driver see their own data
    company_name: Mapped[str | None] = mapped_column(String(128))  # VU overview operator/company
    # The operating company this download names, once it has been cleaned up
    # and matched. Null on driver cards, which never carry one.
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="SET NULL"), index=True)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(BigInteger)  # DH FleetView user who uploaded it
    card_expiry: Mapped[date | None] = mapped_column(Date)  # driver card files: expiry read from the card
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(String(12), server_default=text("'upload'"))  # upload|listener
    parsed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    parse_error: Mapped[str | None] = mapped_column(Text)
    # DVSA retention: keep at least 12 months; do not purge before this instant.
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Infringement(Base):
    __tablename__ = "infringements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    driver_ref: Mapped[str] = mapped_column(String(40), nullable=False)
    rule: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    severity: Mapped[str] = mapped_column(String(14), server_default=text("'serious'"))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    limit_minutes: Mapped[int | None] = mapped_column(Integer)
    actual_minutes: Mapped[int | None] = mapped_column(Integer)
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tacho_files.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(14), server_default=text("'open'"))  # open|acknowledged|dismissed
    # Idempotency: a hash of (driver_ref, rule, period_start) so re-analysing the
    # same data does not duplicate infringements.
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    dedup_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

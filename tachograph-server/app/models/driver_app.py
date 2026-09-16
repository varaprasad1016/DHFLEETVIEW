"""Driver mobile app records that aren't shifts, jobs or walkarounds: fuel
fill-ups and uploaded paperwork (job sheets, PODs, receipts)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FuelLog(Base):
    __tablename__ = "fuel_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    vehicle_reg: Mapped[str] = mapped_column(String(20), nullable=False)
    driver_name: Mapped[str | None] = mapped_column(String(100))
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id", ondelete="SET NULL"))
    fuel_type: Mapped[str] = mapped_column(String(10), server_default=text("'diesel'"))  # diesel|adblue|petrol|electric
    litres: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    odometer_km: Mapped[int | None] = mapped_column(Integer)
    full_tank: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    location: Mapped[str | None] = mapped_column(String(200))
    receipt_path: Mapped[str | None] = mapped_column(String(500))
    content_type: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DriverPaperwork(Base):
    __tablename__ = "driver_paperwork"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    vehicle_reg: Mapped[str | None] = mapped_column(String(20))
    driver_name: Mapped[str | None] = mapped_column(String(100))
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id", ondelete="SET NULL"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(12), server_default=text("'other'"))  # job_sheet|pod|receipt|other
    note: Mapped[str | None] = mapped_column(Text)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

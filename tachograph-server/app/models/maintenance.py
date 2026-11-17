"""Maintenance planner: recurring inspections per vehicle and the records of each one.

Vehicles are DH FleetView devices (traccar_device_id). A schedule is one
recurring item for a vehicle (safety inspection every 6 weeks, tachograph
calibration every 2 years, LOLER every 6 months...). A record is one inspection,
test or service actually carried out, with brake test results and the signed
inspection sheet.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MaintenanceSchedule(Base):
    __tablename__ = "maintenance_schedules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    traccar_device_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    registration: Mapped[str | None] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)          # pmi | mot | tacho_calibration | loler | ...
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    interval_value: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_unit: Mapped[str] = mapped_column(String(8), nullable=False)  # weeks | months
    next_due: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    updated_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MaintenanceRecord(Base):
    __tablename__ = "maintenance_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    traccar_device_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    registration: Mapped[str | None] = mapped_column(String(20))
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("maintenance_schedules.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    due_on: Mapped[date | None] = mapped_column(Date)                     # the planned date it was done against
    performed_on: Mapped[date] = mapped_column(Date, nullable=False)
    performed_by: Mapped[str | None] = mapped_column(String(160))         # garage / inspector
    odometer_km: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[str | None] = mapped_column(String(24))                # pass | advisories | fail
    brake_test_type: Mapped[str | None] = mapped_column(String(24))       # roller_laden | roller_unladen | decelerometer | ebpms
    brake_service_pct: Mapped[float | None] = mapped_column(Numeric(5, 1))
    brake_secondary_pct: Mapped[float | None] = mapped_column(Numeric(5, 1))
    brake_parking_pct: Mapped[float | None] = mapped_column(Numeric(5, 1))
    defects_found: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    document_path: Mapped[str | None] = mapped_column(String(500))
    document_name: Mapped[str | None] = mapped_column(String(200))
    document_type: Mapped[str | None] = mapped_column(String(60))
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

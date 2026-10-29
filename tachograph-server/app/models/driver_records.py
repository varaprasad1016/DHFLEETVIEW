"""Driver compliance records: licence, Driver CPC, tachograph card, medical, ADR.

Kept per DH FleetView driver record (traccar_driver_id), so each company keeps
its own records for a driver who works for several companies.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DriverRecord(Base):
    __tablename__ = "driver_records"

    traccar_driver_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    licence_number: Mapped[str | None] = mapped_column(String(24))
    licence_categories: Mapped[str | None] = mapped_column(String(80))
    licence_expiry: Mapped[date | None] = mapped_column(Date)          # photocard expiry
    licence_checked_on: Mapped[date | None] = mapped_column(Date)      # last DVLA licence check
    licence_points: Mapped[int | None] = mapped_column(Integer)
    licence_check_months: Mapped[int | None] = mapped_column(Integer)  # how often to check (default 6)
    dqc_expiry: Mapped[date | None] = mapped_column(Date)              # Driver CPC qualification card
    card_expiry: Mapped[date | None] = mapped_column(Date)             # tachograph card (else read from downloads)
    medical_expiry: Mapped[date | None] = mapped_column(Date)
    adr_expiry: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DriverCpcCourse(Base):
    __tablename__ = "driver_cpc_courses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    traccar_driver_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    course_date: Mapped[date] = mapped_column(Date, nullable=False)
    hours: Mapped[float] = mapped_column(Numeric(4, 1), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(160))
    certificate_path: Mapped[str | None] = mapped_column(String(500))
    certificate_name: Mapped[str | None] = mapped_column(String(200))
    certificate_type: Mapped[str | None] = mapped_column(String(60))
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

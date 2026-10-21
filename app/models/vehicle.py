"""Vehicle status from DVLA: MOT, tax, and the emissions data (Euro status,
fuel type) that also drives Clean Air Zone charge exposure.

One row per registration the fleet monitors. `last_checked` is when DVLA was
last queried; a blank api key means rows exist but are never refreshed.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VehicleStatus(Base):
    __tablename__ = "vehicle_status"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    reg: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # normalised, no spaces

    make: Mapped[str | None] = mapped_column(String(40))
    colour: Mapped[str | None] = mapped_column(String(30))
    year: Mapped[int | None] = mapped_column(Integer)
    fuel_type: Mapped[str | None] = mapped_column(String(30))        # PETROL, DIESEL, ELECTRIC, ...
    co2: Mapped[int | None] = mapped_column(Integer)
    euro_status: Mapped[str | None] = mapped_column(String(20))      # e.g. "EURO 6", may be null from DVLA
    engine_capacity: Mapped[int | None] = mapped_column(Integer)

    tax_status: Mapped[str | None] = mapped_column(String(30))       # Taxed, Untaxed, SORN
    tax_due_date: Mapped[date | None] = mapped_column(Date)
    mot_status: Mapped[str | None] = mapped_column(String(30))       # Valid, Not valid, No details held
    mot_expiry_date: Mapped[date | None] = mapped_column(Date)
    marked_for_export: Mapped[bool | None] = mapped_column(Boolean)

    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

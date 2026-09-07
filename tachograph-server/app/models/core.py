"""Core entity models: devices, drivers, assignments, company cards, TBA instances."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = _pk()
    imei: Mapped[str] = mapped_column(String(15), unique=True, nullable=False)
    vehicle_reg: Mapped[str | None] = mapped_column(String(20))
    vin: Mapped[str | None] = mapped_column(String(17))
    model: Mapped[str | None] = mapped_column(String(20))            # FMB640, FMC650, ...
    firmware_version: Mapped[str | None] = mapped_column(String(30))
    tacho_type: Mapped[str | None] = mapped_column(String(50))       # DTCO 1381, SE5000, ...
    protocol_path: Mapped[str | None] = mapped_column(String(2))     # 'A' or 'B'
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str | None] = mapped_column(String(100))
    card_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    created_at: Mapped[datetime] = _created()


class DriverAssignment(Base):
    __tablename__ = "driver_assignments"

    driver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drivers.id"), primary_key=True)
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), primary_key=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CompanyCard(Base):
    __tablename__ = "company_cards"

    id: Mapped[uuid.UUID] = _pk()
    card_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # TBA card_id
    name: Mapped[str | None] = mapped_column(String(100))
    number: Mapped[str | None] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = _created()


class TbaInstance(Base):
    __tablename__ = "tba_instances"

    id: Mapped[uuid.UUID] = _pk()
    tba_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = _created()

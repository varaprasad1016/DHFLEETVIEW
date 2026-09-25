"""Core entity models: devices, drivers, assignments, company cards, TBA instances."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Company(Base):
    """A customer tenant. Vehicles, cards, bridge instances and VU files belong to it."""

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    account_code: Mapped[str | None] = mapped_column(String(40), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = _created()


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vehicles.id"))
    imei: Mapped[str] = mapped_column(String(15), unique=True, nullable=False)
    vehicle_reg: Mapped[str | None] = mapped_column(String(20))
    vin: Mapped[str | None] = mapped_column(String(17))
    model: Mapped[str | None] = mapped_column(String(20))            # FMB640, FMC650, ...
    firmware_version: Mapped[str | None] = mapped_column(String(30))
    tacho_type: Mapped[str | None] = mapped_column(String(50))       # DTCO 1381, SE5000, ...
    protocol_path: Mapped[str | None] = mapped_column(String(2))     # 'A' or 'B'
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class Vehicle(Base):
    """Customer-owned vehicle and its installed FMC650/tachograph identity."""

    __tablename__ = "vehicles"
    __table_args__ = (UniqueConstraint("company_id", "registration", name="uq_vehicle_company_registration"),)

    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    registration: Mapped[str] = mapped_column(String(20), nullable=False)
    vin: Mapped[str | None] = mapped_column(String(17))
    tachograph_serial: Mapped[str | None] = mapped_column(String(50))
    # Which company actually operates this vehicle, read from its own unit.
    # Separate from company_id above, which is the billing tenant: one customer
    # login can hold trucks run by several different legal entities.
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("operators.id", ondelete="SET NULL"), index=True)
    fmc650_imei: Mapped[str | None] = mapped_column(String(15))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = _created()


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str | None] = mapped_column(String(100))
    card_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    created_at: Mapped[datetime] = _created()


class DriverCompany(Base):
    """Many-to-many employment/association; a driver may work for many customers."""

    __tablename__ = "driver_companies"

    driver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drivers.id", ondelete="CASCADE"), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    card_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # TBA card_id
    name: Mapped[str | None] = mapped_column(String(100))
    number: Mapped[str | None] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = _created()


class TbaInstance(Base):
    __tablename__ = "tba_instances"

    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"))
    name: Mapped[str | None] = mapped_column(String(100))
    ws_url: Mapped[str | None] = mapped_column(String(500))
    tba_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = _created()

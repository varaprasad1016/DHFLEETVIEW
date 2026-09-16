"""Driver shift tracking with clock in/out, breaks, and job assignments.

Drivers clock in by uploading odometer, fuel, and AdBlue photos. Jobs are
sent by owners and must be accepted/denied before appearing in the driver's
active shift. Breaks and shift end complete the workflow.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Shift(Base):
    """A driver's work shift, from clock-in to clock-out."""
    __tablename__ = "shifts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drivers.id"))
    driver_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # The company's DH FleetView driver record this belongs to (company scoping).
    traccar_driver_id: Mapped[int | None] = mapped_column(BigInteger)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"))
    vehicle_reg: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(
        String(20), server_default=text("'clocked_in'"))  # clocked_in|on_break|active|clocked_out

    # Clock-in readings
    odometer_km: Mapped[int | None] = mapped_column(Integer)
    fuel_level_pct: Mapped[int | None] = mapped_column(Integer)
    adblue_level_pct: Mapped[int | None] = mapped_column(Integer)

    # Clock-out readings
    odometer_out_km: Mapped[int | None] = mapped_column(Integer)
    fuel_level_out_pct: Mapped[int | None] = mapped_column(Integer)
    adblue_level_out_pct: Mapped[int | None] = mapped_column(Integer)

    notes: Mapped[str | None] = mapped_column(Text)
    clocked_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    break_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    break_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clocked_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    photos: Mapped[list["ShiftPhoto"]] = relationship(
        back_populates="shift", cascade="all, delete-orphan")
    jobs: Mapped[list["ShiftJob"]] = relationship(
        back_populates="shift", cascade="all, delete-orphan")


class ShiftPhoto(Base):
    """Photos uploaded during clock-in or clock-out (odometer, fuel, AdBlue)."""
    __tablename__ = "shift_photos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False)
    photo_type: Mapped[str] = mapped_column(
        String(30), nullable=False)  # odometer_in|fuel_in|adblue_in|odometer_out|fuel_out|adblue_out
    content_type: Mapped[str] = mapped_column(
        String(40), server_default=text("'image/jpeg'"))
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    shift: Mapped["Shift"] = relationship(back_populates="photos")


class Job(Base):
    """A job sent by owner/admin to a driver."""
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"))
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drivers.id"))
    driver_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # The company's DH FleetView driver record this belongs to (company scoping).
    traccar_driver_id: Mapped[int | None] = mapped_column(BigInteger)
    vehicle_reg: Mapped[str | None] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    pickup_location: Mapped[str | None] = mapped_column(String(300))
    dropoff_location: Mapped[str | None] = mapped_column(String(300))
    priority: Mapped[str] = mapped_column(
        String(10), server_default=text("'normal'"))  # low|normal|urgent
    status: Mapped[str] = mapped_column(
        String(20), server_default=text("'pending'"))  # pending|accepted|in_progress|denied|completed|cancelled
    # Human job number shown to drivers as JOB-<number>; filled by job_number_seq.
    number: Mapped[int] = mapped_column(
        Integer, server_default=text("nextval('job_number_seq')"), nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_by: Mapped[str | None] = mapped_column(String(100))
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    denied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deny_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    shift_jobs: Mapped[list["ShiftJob"]] = relationship(
        back_populates="job", cascade="all, delete-orphan")
    messages: Mapped[list["JobMessage"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobMessage.created_at")


class JobMessage(Base):
    """Driver <-> office thread on a job; `kind='change'` flags a reported change."""
    __tablename__ = "job_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    sender: Mapped[str] = mapped_column(String(10), server_default=text("'driver'"))  # driver|office
    author: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(12), server_default=text("'message'"))  # message|change
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    job: Mapped["Job"] = relationship(back_populates="messages")


class ShiftJob(Base):
    """Links a job to a shift when the driver accepts it."""
    __tablename__ = "shift_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    shift: Mapped["Shift"] = relationship(back_populates="jobs")
    job: Mapped["Job"] = relationship(back_populates="shift_jobs")

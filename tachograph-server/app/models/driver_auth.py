"""Driver sign-in: one account per driver (name + PIN, set up by the office)
and long-lived device sessions for the driver app."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DriverAccount(Base):
    __tablename__ = "driver_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    # Matches Shift/Job.driver_name. Copied from the DH FleetView driver.
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Legacy single-company link (now in driver_memberships), and the person's
    # identifier (driver card number or mobile), unique across companies.
    traccar_driver_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    unique_id: Mapped[str | None] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(30))
    pin_hash: Mapped[str] = mapped_column(String(200), nullable=False)  # scrypt$salt$hash (hex)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    failed_attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DriverSession(Base):
    __tablename__ = "driver_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("driver_accounts.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)  # sha256 hex; token never stored
    user_agent: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DriverMembership(Base):
    """A driver login's link to one company: that company's DH FleetView driver record."""

    __tablename__ = "driver_memberships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("driver_accounts.id", ondelete="CASCADE"), nullable=False)
    traccar_driver_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    company_label: Mapped[str | None] = mapped_column(String(160))   # the DH FleetView account that added the driver
    owner_user_id: Mapped[int | None] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

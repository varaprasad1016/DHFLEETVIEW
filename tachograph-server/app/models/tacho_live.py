"""Live tachograph data from FMC650 trackers (provisional until a download).

- TachoLiveStatus: the latest known state of each driver slot in each vehicle.
- TachoLiveActivity: activity spans built from working-state changes. They are
  provisional: a driver-card download covering the same time replaces them.
- TachoLiveAlert: things the office should act on (driving without a card,
  limits reached).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TachoLiveStatus(Base):
    __tablename__ = "tacho_live_status"
    __table_args__ = (UniqueConstraint("device_uid", "slot", name="uq_tacho_live_status_device_slot"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    device_uid: Mapped[str] = mapped_column(String(40), nullable=False)       # tracker IMEI (DH FleetView identifier)
    traccar_device_id: Mapped[int | None] = mapped_column(BigInteger)
    vehicle_name: Mapped[str | None] = mapped_column(String(120))
    vehicle_reg: Mapped[str | None] = mapped_column(String(20), index=True)   # normalised
    slot: Mapped[int] = mapped_column(Integer, nullable=False)                 # 1 driver, 2 co-driver
    card_number: Mapped[str | None] = mapped_column(String(32), index=True)
    card_holder: Mapped[str | None] = mapped_column(String(120))
    card_present: Mapped[bool | None] = mapped_column(Boolean)
    working_state: Mapped[str | None] = mapped_column(String(12))
    state_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_state: Mapped[int | None] = mapped_column(Integer)
    no_card_driving: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    values: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TachoLiveActivity(Base):
    __tablename__ = "tacho_live_activities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    device_uid: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    vehicle_reg: Mapped[str | None] = mapped_column(String(20))
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    card_number: Mapped[str | None] = mapped_column(String(32), index=True)
    activity_type: Mapped[str] = mapped_column(String(12), nullable=False)    # drive|work|available|rest
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))   # None = still going
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TachoLiveAlert(Base):
    __tablename__ = "tacho_live_alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)          # no_card_driving | limit_<code>
    device_uid: Mapped[str] = mapped_column(String(40), nullable=False)
    vehicle_reg: Mapped[str | None] = mapped_column(String(20))
    slot: Mapped[int | None] = mapped_column(Integer)
    card_number: Mapped[str | None] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(120))
    dedup_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

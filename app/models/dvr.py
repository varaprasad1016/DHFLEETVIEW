"""DVR setup by text message: the commands that bring a camera online, and what was sent.

A new DVR needs a handful of SMS commands before it will talk to the server at
all. They are kept here so they can be sent from the platform and seen later,
rather than typed into a phone each time.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DvrCommand(Base):
    __tablename__ = "dvr_commands"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(80))
    body: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str | None] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DvrMessage(Base):
    """One text message: queued here, picked up by the sending phone, then marked sent."""

    __tablename__ = "dvr_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    to_number: Mapped[str] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(Text)
    device_id: Mapped[int | None] = mapped_column(BigInteger)
    device_name: Mapped[str | None] = mapped_column(String(120))
    command_name: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="queued")   # queued | sending | sent | failed
    detail: Mapped[str | None] = mapped_column(Text)
    queued_by: Mapped[str | None] = mapped_column(String(120))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

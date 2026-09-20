"""Tacho Bridge App sign-ins and the apps, company cards and card racks seen on them.

A sign-in (username + password) belongs to one DH FleetView account (company).
Everything that connects with it - the app, the company cards in its readers,
the Lisle card racks on its COM ports - belongs to that company too.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BridgeCredential(Base):
    __tablename__ = "bridge_credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    owner_name: Mapped[str | None] = mapped_column(String(160))
    label: Mapped[str | None] = mapped_column(String(80))
    username: Mapped[str] = mapped_column(String(40), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BridgeNode(Base):
    """An app instance (kind=app, key=TBA ident), a company card (kind=card, key=card
    number) or a card rack (kind=rack, key=rack serial) last seen for a company."""

    __tablename__ = "bridge_nodes"
    __table_args__ = (UniqueConstraint("owner_user_id", "kind", "key", name="uq_bridge_nodes_owner_kind_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(8))
    key: Mapped[str] = mapped_column(String(64))
    credential_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    info: Mapped[dict | None] = mapped_column(JSONB)
    remote_addr: Mapped[str | None] = mapped_column(String(64))
    # The company a card belongs to: the account whose vehicles it may download,
    # and the only account its files are visible to. Set on the Tachograph page.
    assigned_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    assigned_name: Mapped[str | None] = mapped_column(String(160))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

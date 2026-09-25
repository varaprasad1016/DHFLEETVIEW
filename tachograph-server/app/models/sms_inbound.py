"""What came back from a camera: its replies, and receipts for what we sent.

Caburn post these to us as they arrive rather than us asking for them. Their
documentation is explicit that an item can be delivered more than once if a
response is not received, so each carries a delivery id we keep unique - a
reply shown twice would have an operator chasing a camera that already answered.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SmsInbound(Base):
    """One thing posted to us: a reply from a camera, or a delivery receipt."""

    __tablename__ = "sms_inbound"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True,
                                          server_default=text("gen_random_uuid()"))
    # Caburn's own reference for the delivery. Unique, so a repeat is ignored.
    delivery_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)   # reply | receipt
    iccid: Mapped[str | None] = mapped_column(String(32), index=True)
    msisdn: Mapped[str | None] = mapped_column(String(32), index=True)
    body: Mapped[str | None] = mapped_column(Text)
    # Receipts only: which message this is about, and how it went.
    sms_uid: Mapped[str | None] = mapped_column(String(16), index=True)
    status: Mapped[str | None] = mapped_column(String(32))
    happened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  server_default=func.now(), index=True)
    raw: Mapped[str | None] = mapped_column(Text)

"""A record of every email the platform has sent by itself.

Two things need this. The first is that an automatic send must not happen
twice: the server restarting on a Monday morning, or a run being started by
hand while the scheduled one is going, would otherwise email the same customer
the same invoice again. A row per (job, period, recipient) makes the second
attempt a no-op.

The second is that nobody believes "it was emailed" without evidence. Every
attempt is kept, the failures included, with whatever the mail server said.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EmailSend(Base):
    """One attempt to email one thing to one address."""

    __tablename__ = "email_sends"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True,
                                          default=uuid.uuid4)
    # Which job this belongs to: "invoice" or "driver_report".
    kind: Mapped[str] = mapped_column(String(32), index=True)
    # The period it covers, in the form the job counts in: "2026-Q3", "2026-W39".
    period_key: Mapped[str] = mapped_column(String(32), index=True)
    # What was sent - an invoice number, or the account the reports were for.
    reference: Mapped[str | None] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    account_name: Mapped[str | None] = mapped_column(String(200))
    recipient: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str | None] = mapped_column(String(300))
    # sent | failed | skipped
    status: Mapped[str] = mapped_column(String(16), index=True)
    detail: Mapped[str | None] = mapped_column(Text)
    # False when somebody pressed Send themselves. Only automatic sends are
    # deduplicated: pressing Send again is a deliberate act and always goes.
    automatic: Mapped[bool] = mapped_column(Boolean, default=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

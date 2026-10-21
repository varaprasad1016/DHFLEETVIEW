"""Monthly licence state.

A single row per server_id holds the paired phone's public key and the latest
approved cycle. The tacho download listeners consult this before accepting a
download; GPS/Traccar is a separate service and is never gated here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LicenseState(Base):
    __tablename__ = "license_state"

    # Logical singleton, keyed by the configured server id.
    server_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Base64 of the phone's raw ECDSA P-256 public point (0x04||X||Y), set once
    # at pairing. None means unpaired -> tacho stays suspended.
    public_key: Mapped[str | None] = mapped_column(String(256))
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Latest approved cycle: period id "YYYY-MM" (the cycle's starting 15th),
    # and the instant the licence lapses (the next 15th, 00:00 UTC).
    period: Mapped[str | None] = mapped_column(String(7))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

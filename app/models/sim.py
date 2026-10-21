"""The SIMs we hold, whether or not they are in a vehicle yet.

Caburn's API answers about one SIM at a time and has no call that lists an
account's SIMs, so the stock we hold comes from a CSV exported from their
portal. A SIM stays here once imported: assigning it to a vehicle records
which vehicle, rather than moving the row somewhere else, so a SIM taken out
of a vehicle is still known about.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SimCard(Base):
    __tablename__ = "sim_cards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True,
                                          server_default=text("gen_random_uuid()"))
    # The ICCID identifies a SIM for good; a number can be reassigned.
    iccid: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    msisdn: Mapped[str | None] = mapped_column(String(32), index=True)
    sim_no: Mapped[str | None] = mapped_column(String(50))
    # What the portal said when it was exported. The live status is asked for
    # separately; this is only what we were told at import.
    status: Mapped[str | None] = mapped_column(String(32))
    group: Mapped[str | None] = mapped_column(String(80))
    network: Mapped[str | None] = mapped_column(String(80))
    # The unit the SIM is actually in, as the network sees it.
    imei: Mapped[str | None] = mapped_column(String(32), index=True)
    data_mb: Mapped[float | None] = mapped_column(Float)
    # The level at which the provider warns, and the level at which it cuts
    # the SIM off entirely - which is how a camera goes dark mid-month.
    warning_mb: Mapped[float | None] = mapped_column(Float)
    limit_mb: Mapped[float | None] = mapped_column(Float)
    # What the network itself last answered, and when it was asked. Kept apart
    # from `status` above, which is only what the exported spreadsheet said.
    live_status: Mapped[str | None] = mapped_column(String(32))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When the SIM was first confirmed active through this platform, and by whom.
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_by: Mapped[str | None] = mapped_column(String(120))
    # Where it is fitted, once someone assigns it.
    device_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    vehicle: Mapped[str | None] = mapped_column(String(64))
    fitted: Mapped[str | None] = mapped_column(String(16))   # camera | tracker
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_by: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  server_default=func.now())

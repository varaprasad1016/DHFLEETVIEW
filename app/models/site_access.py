"""Who reached the site, from where, on what.

The web server has always written an access log, but a 60 MB text file nobody
rotates is not a record anyone can answer a question from. This is the same
traffic folded into one row per address, per device, per day: how many requests
it made, when it first and last appeared, what it used, and - where a sign-in
can be matched to it - which account was behind it.

Kept deliberately coarse. The question a fleet operator actually asks is "who
has been getting into my system and from where", not "what did this person
request at 14:03", and a row per request would be a surveillance log of their
own staff that nobody asked for and the Data Protection Act would frown at.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SiteAccess(Base):
    __tablename__ = "site_access"
    __table_args__ = (
        UniqueConstraint("day", "address", "agent_hash", name="uq_site_access_day_address_agent"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True,
                                          server_default=text("gen_random_uuid()"))
    day: Mapped[date] = mapped_column(Date, index=True)
    address: Mapped[str] = mapped_column(String(45), index=True)      # fits IPv6
    # The full user agent is kept for diagnosis; the hash is what makes the row
    # unique, because agent strings are long and repeat endlessly.
    agent: Mapped[str] = mapped_column(String(400))
    agent_hash: Mapped[str] = mapped_column(String(32))
    device: Mapped[str] = mapped_column(String(40))                   # iPhone, Windows PC, ...
    browser: Mapped[str] = mapped_column(String(40))

    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    # Requests that only a signed-in person or an app makes, as opposed to a
    # crawler hitting the front page.
    app_requests: Mapped[int] = mapped_column(Integer, default=0)
    sign_ins: Mapped[int] = mapped_column(Integer, default=0)
    refused: Mapped[int] = mapped_column(Integer, default=0)          # 401/403 answers

    # What they used, as a short list: "fleet app, video, tacho pages".
    used: Mapped[str | None] = mapped_column(String(120))
    # The account behind it, matched from the sign-in audit where possible.
    account: Mapped[str | None] = mapped_column(String(200), index=True)
    # Crawlers and scanners announce themselves; kept, but flagged so the list
    # of real people is not buried in them.
    robot: Mapped[bool] = mapped_column(default=False, index=True)


class SiteAccessCursor(Base):
    """How far through the web server's log we have read.

    The log is appended to constantly and rotated occasionally, so the position
    alone is not enough: the size is kept too, and a file that has shrunk is
    read again from the beginning rather than skipped.
    """

    __tablename__ = "site_access_cursor"

    path: Mapped[str] = mapped_column(String(300), primary_key=True)
    offset: Mapped[int] = mapped_column(Integer, default=0)
    size: Mapped[int] = mapped_column(Integer, default=0)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

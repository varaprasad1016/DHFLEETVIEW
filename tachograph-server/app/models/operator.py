"""Who actually operates a vehicle, as opposed to who pays the bill.

One customer often runs several legal entities - separate O-licences, separate
company names on the paperwork - while keeping every unit in a single
DH FleetView login because that is how they want to see their fleet. Billing
follows the login. Tachograph paperwork must not: a driver's report has to
carry the name of the company that actually operates the truck, or it is the
wrong document.

So the operator is kept apart from the billing tenant entirely. It comes from
the vehicle unit itself - a tachograph is locked to a company card, and every
VU download carries that company's name - which makes it independent of how
somebody chose to organise their account, and the only source that cannot be
got wrong by tidying up a login.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Operator(Base):
    __tablename__ = "operators"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True,
                                          server_default=text("gen_random_uuid()"))
    # As it reads on the paperwork, exactly as the tachograph recorded it.
    name: Mapped[str] = mapped_column(String(160))
    # The same name reduced to something comparable, so "A B Haulage Ltd" and
    # "A B HAULAGE LIMITED" are recognised as one company rather than two.
    match_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    # Where reports for this operator go. Blank until somebody sets it; the
    # per-operator send is a later step and refuses to guess.
    contact_email: Mapped[str | None] = mapped_column(String(200))
    # download = read from a vehicle unit; manual = somebody typed it.
    source: Mapped[str] = mapped_column(String(16), server_default=text("'download'"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())

"""Invoices sent to customers, and what each account is charged.

An invoice is kept as its own record rather than rebuilt on demand: once it has
gone to a customer it must never change, even if a vehicle is later removed or
a rate is revised. The lines are stored with it for the same reason - they are
what the customer was told, not what today's data would say.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric,
                        String, Text, func, text)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BillingAccount(Base):
    """What one customer account is charged, and where its invoices go.

    One row per Traccar account that is billed. An account with no row here is
    not invoiced at all, so a new customer is never billed by accident.
    """

    __tablename__ = "billing_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True,
                                          server_default=text("gen_random_uuid()"))
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    # Where invoices are sent. The account's own email is used unless the
    # customer asks for them to go somewhere else - accounts departments
    # are rarely the person who signed up.
    account_email: Mapped[str | None] = mapped_column(String(200))
    invoicing_email: Mapped[str | None] = mapped_column(String(200))
    # The day billing starts. The first invoice runs from here to month end.
    started_on: Mapped[date] = mapped_column(Date)
    # Blank rates fall back to the server's standard rates.
    rate_tracking: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    rate_camera: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    rate_tachograph: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def send_to(self) -> str | None:
        return self.invoicing_email or self.account_email


class Invoice(Base):
    """One month's invoice for one account, as it was sent."""

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True,
                                          server_default=text("gen_random_uuid()"))
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    account_name: Mapped[str] = mapped_column(String(200))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    issued_on: Mapped[date] = mapped_column(Date)
    net: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    vat: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    # draft -> sent, or failed if the email would not go.
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    sent_to: Mapped[str | None] = mapped_column(String(200))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceLine.position")


class InvoiceLine(Base):
    """One charge on an invoice, kept as it was worked out at the time."""

    __tablename__ = "invoice_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True,
                                          server_default=text("gen_random_uuid()"))
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    vehicle: Mapped[str] = mapped_column(String(64))
    item: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(String(200))
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    days: Mapped[int] = mapped_column(Integer)
    days_in_month: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    invoice: Mapped[Invoice] = relationship(back_populates="lines")

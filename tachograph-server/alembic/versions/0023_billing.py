"""customer billing accounts and the invoices sent to them

Revision ID: 0023_billing
Revises: 0022_dvr_commands
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0023_billing"
down_revision = "0022_dvr_commands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.BigInteger, nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("account_email", sa.String(200)),
        sa.Column("invoicing_email", sa.String(200)),
        sa.Column("started_on", sa.Date, nullable=False),
        sa.Column("rate_tracking", sa.Numeric(10, 2)),
        sa.Column("rate_camera", sa.Numeric(10, 2)),
        sa.Column("rate_tachograph", sa.Numeric(10, 2)),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_billing_accounts_user_id", "billing_accounts", ["user_id"])

    op.create_table(
        "invoices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("number", sa.String(32), nullable=False, unique=True),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("account_name", sa.String(200), nullable=False),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("issued_on", sa.Date, nullable=False),
        sa.Column("net", sa.Numeric(10, 2), nullable=False),
        sa.Column("vat", sa.Numeric(10, 2), nullable=False),
        sa.Column("total", sa.Numeric(10, 2), nullable=False),
        sa.Column("vat_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("sent_to", sa.String(200)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("detail", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_invoices_user_id", "invoices", ["user_id"])
    op.create_index("ix_invoices_status", "invoices", ["status"])
    # One invoice per account per period: a re-run of the monthly job must not
    # be able to bill a customer twice for the same month.
    op.create_unique_constraint("uq_invoices_account_period", "invoices",
                                ["user_id", "period_start", "period_end"])

    op.create_table(
        "invoice_lines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("invoice_id", UUID(as_uuid=True),
                  sa.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("vehicle", sa.String(64), nullable=False),
        sa.Column("item", sa.String(32), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("rate", sa.Numeric(10, 2), nullable=False),
        sa.Column("days", sa.Integer, nullable=False),
        sa.Column("days_in_month", sa.Integer, nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
    )
    op.create_index("ix_invoice_lines_invoice_id", "invoice_lines", ["invoice_id"])


def downgrade() -> None:
    op.drop_table("invoice_lines")
    op.drop_table("invoices")
    op.drop_table("billing_accounts")

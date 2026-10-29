"""replies from cameras, and delivery receipts for what we sent

Revision ID: 0024_sms_inbound
Revises: 0023_billing
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0024_sms_inbound"
down_revision = "0023_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sms_inbound",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        # Their delivery id. Unique: they may post the same item twice.
        sa.Column("delivery_id", sa.String(40), nullable=False, unique=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("iccid", sa.String(32)),
        sa.Column("msisdn", sa.String(32)),
        sa.Column("body", sa.Text),
        sa.Column("sms_uid", sa.String(16)),
        sa.Column("status", sa.String(32)),
        sa.Column("happened_at", sa.DateTime(timezone=True)),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("raw", sa.Text),
    )
    op.create_index("ix_sms_inbound_delivery_id", "sms_inbound", ["delivery_id"])
    op.create_index("ix_sms_inbound_kind", "sms_inbound", ["kind"])
    op.create_index("ix_sms_inbound_msisdn", "sms_inbound", ["msisdn"])
    op.create_index("ix_sms_inbound_iccid", "sms_inbound", ["iccid"])
    op.create_index("ix_sms_inbound_sms_uid", "sms_inbound", ["sms_uid"])
    op.create_index("ix_sms_inbound_received_at", "sms_inbound", ["received_at"])


def downgrade() -> None:
    op.drop_table("sms_inbound")

"""the SIMs we hold, imported from the provider's portal

Revision ID: 0025_sim_cards
Revises: 0024_sms_inbound
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0025_sim_cards"
down_revision = "0024_sms_inbound"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sim_cards",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("iccid", sa.String(32), nullable=False, unique=True),
        sa.Column("msisdn", sa.String(32)),
        sa.Column("sim_no", sa.String(50)),
        sa.Column("status", sa.String(32)),
        sa.Column("group", sa.String(80)),
        sa.Column("network", sa.String(80)),
        sa.Column("imei", sa.String(32)),
        sa.Column("data_mb", sa.Float),
        sa.Column("device_id", sa.BigInteger),
        sa.Column("vehicle", sa.String(64)),
        sa.Column("fitted", sa.String(16)),
        sa.Column("assigned_at", sa.DateTime(timezone=True)),
        sa.Column("assigned_by", sa.String(120)),
        sa.Column("notes", sa.Text),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sim_cards_iccid", "sim_cards", ["iccid"])
    op.create_index("ix_sim_cards_msisdn", "sim_cards", ["msisdn"])
    op.create_index("ix_sim_cards_device_id", "sim_cards", ["device_id"])
    op.create_index("ix_sim_cards_imei", "sim_cards", ["imei"])


def downgrade() -> None:
    op.drop_table("sim_cards")

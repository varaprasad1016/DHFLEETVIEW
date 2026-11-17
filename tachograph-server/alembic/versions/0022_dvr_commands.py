"""saved DVR setup commands and the messages sent from them

Revision ID: 0022_dvr_commands
Revises: 0021_bridge_card_company
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0022_dvr_commands"
down_revision = "0021_bridge_card_company"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dvr_commands",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.String(120)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "dvr_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("to_number", sa.String(32), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("device_id", sa.BigInteger),
        sa.Column("device_name", sa.String(120)),
        sa.Column("command_name", sa.String(80)),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("detail", sa.Text),
        sa.Column("queued_by", sa.String(120)),
        sa.Column("queued_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_dvr_messages_status", "dvr_messages", ["status"])


def downgrade() -> None:
    op.drop_index("ix_dvr_messages_status", table_name="dvr_messages")
    op.drop_table("dvr_messages")
    op.drop_table("dvr_commands")

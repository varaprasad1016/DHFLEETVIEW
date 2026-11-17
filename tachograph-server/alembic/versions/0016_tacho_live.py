"""live tachograph data from FMC650 trackers

Revision ID: 0016_tacho_live
Revises: 0015_tacho_file_uploader
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0016_tacho_live"
down_revision = "0015_tacho_file_uploader"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tacho_live_status",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("device_uid", sa.String(40), nullable=False),
        sa.Column("traccar_device_id", sa.BigInteger),
        sa.Column("vehicle_name", sa.String(120)),
        sa.Column("vehicle_reg", sa.String(20)),
        sa.Column("slot", sa.Integer, nullable=False),
        sa.Column("card_number", sa.String(32)),
        sa.Column("card_holder", sa.String(120)),
        sa.Column("card_present", sa.Boolean),
        sa.Column("working_state", sa.String(12)),
        sa.Column("state_since", sa.DateTime(timezone=True)),
        sa.Column("time_state", sa.Integer),
        sa.Column("no_card_driving", sa.Boolean, server_default=sa.text("false")),
        sa.Column("values", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("device_uid", "slot", name="uq_tacho_live_status_device_slot"),
    )
    op.create_index("ix_tacho_live_status_card_number", "tacho_live_status", ["card_number"])
    op.create_index("ix_tacho_live_status_vehicle_reg", "tacho_live_status", ["vehicle_reg"])

    op.create_table(
        "tacho_live_activities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("device_uid", sa.String(40), nullable=False),
        sa.Column("vehicle_reg", sa.String(20)),
        sa.Column("slot", sa.Integer, nullable=False),
        sa.Column("card_number", sa.String(32)),
        sa.Column("activity_type", sa.String(12), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tacho_live_activities_device_uid", "tacho_live_activities", ["device_uid"])
    op.create_index("ix_tacho_live_activities_card_number", "tacho_live_activities", ["card_number"])
    op.create_index("ix_tacho_live_activities_started_at", "tacho_live_activities", ["started_at"])

    op.create_table(
        "tacho_live_alerts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("device_uid", sa.String(40), nullable=False),
        sa.Column("vehicle_reg", sa.String(20)),
        sa.Column("slot", sa.Integer),
        sa.Column("card_number", sa.String(32)),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_by", sa.String(120)),
        sa.Column("dedup_key", sa.String(160), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tacho_live_alerts_card_number", "tacho_live_alerts", ["card_number"])


def downgrade() -> None:
    op.drop_table("tacho_live_alerts")
    op.drop_table("tacho_live_activities")
    op.drop_table("tacho_live_status")

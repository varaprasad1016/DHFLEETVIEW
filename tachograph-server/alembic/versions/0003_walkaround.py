"""walkaround checks and defects

Revision ID: 0003_walkaround
Revises: 0002_license_state
Create Date: 2026-09-08

Hand-written (no autogenerate) per project policy. Mirrors app/models/walkaround.py.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0003_walkaround"
down_revision = "0002_license_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "walkaround_checks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("vehicle_reg", sa.String(20), nullable=False),
        sa.Column("driver_name", sa.String(100)),
        sa.Column("check_type", sa.String(10), server_default=sa.text("'hgv'")),
        sa.Column("odometer_km", sa.Integer),
        sa.Column("location", sa.String(200)),
        sa.Column("result", sa.String(10), server_default=sa.text("'pass'")),
        sa.Column("safe_to_drive", sa.Boolean, server_default=sa.text("true")),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_walkaround_checks_reg", "walkaround_checks", ["vehicle_reg"])
    op.create_index("ix_walkaround_checks_created", "walkaround_checks", ["created_at"])

    op.create_table(
        "walkaround_defects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("check_id", UUID(as_uuid=True),
                  sa.ForeignKey("walkaround_checks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vehicle_reg", sa.String(20), nullable=False),
        sa.Column("item", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(10), server_default=sa.text("'major'")),
        sa.Column("description", sa.Text),
        sa.Column("photo_key", sa.String(500)),
        sa.Column("status", sa.String(12), server_default=sa.text("'open'")),
        sa.Column("reported_by", sa.String(100)),
        sa.Column("rectified_by", sa.String(100)),
        sa.Column("rectification_notes", sa.Text),
        sa.Column("rectified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_walkaround_defects_status", "walkaround_defects", ["status"])
    op.create_index("ix_walkaround_defects_reg", "walkaround_defects", ["vehicle_reg"])


def downgrade() -> None:
    op.drop_table("walkaround_defects")
    op.drop_table("walkaround_checks")

"""vehicle status (DVLA MOT/tax/emissions)

Revision ID: 0005_vehicle_status
Revises: 0004_tacho_compliance
Create Date: 2026-09-08

Hand-written (no autogenerate) per project policy. Mirrors app/models/vehicle.py.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0005_vehicle_status"
down_revision = "0004_tacho_compliance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vehicle_status",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("reg", sa.String(20), nullable=False, unique=True),
        sa.Column("make", sa.String(40)),
        sa.Column("colour", sa.String(30)),
        sa.Column("year", sa.Integer),
        sa.Column("fuel_type", sa.String(30)),
        sa.Column("co2", sa.Integer),
        sa.Column("euro_status", sa.String(20)),
        sa.Column("engine_capacity", sa.Integer),
        sa.Column("tax_status", sa.String(30)),
        sa.Column("tax_due_date", sa.Date),
        sa.Column("mot_status", sa.String(30)),
        sa.Column("mot_expiry_date", sa.Date),
        sa.Column("marked_for_export", sa.Boolean),
        sa.Column("last_checked", sa.DateTime(timezone=True)),
        sa.Column("check_error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("vehicle_status")

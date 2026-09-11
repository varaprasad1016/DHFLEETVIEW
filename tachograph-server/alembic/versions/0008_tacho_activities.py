"""canonical tachograph activity spans

Revision ID: 0008_tacho_activities
Revises: 0007_customer_tenancy
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0008_tacho_activities"
down_revision = "0007_customer_tenancy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tacho_activities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id")),
        sa.Column("source_file_id", UUID(as_uuid=True), sa.ForeignKey("tacho_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("driver_id", UUID(as_uuid=True), sa.ForeignKey("drivers.id")),
        sa.Column("vehicle_id", UUID(as_uuid=True), sa.ForeignKey("vehicles.id")),
        sa.Column("driver_ref", sa.String(40)),
        sa.Column("vehicle_ref", sa.String(20)),
        sa.Column("activity_type", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(20), server_default=sa.text("'TACHOGRAPH'")),
        sa.Column("confidence", sa.String(16), server_default=sa.text("'DIRECT'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tacho_activities_file", "tacho_activities", ["source_file_id"])
    op.create_index("ix_tacho_activities_driver_time", "tacho_activities", ["driver_ref", "started_at"])
    op.create_index("ix_tacho_activities_vehicle_time", "tacho_activities", ["vehicle_ref", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_tacho_activities_vehicle_time", table_name="tacho_activities")
    op.drop_index("ix_tacho_activities_driver_time", table_name="tacho_activities")
    op.drop_index("ix_tacho_activities_file", table_name="tacho_activities")
    op.drop_table("tacho_activities")

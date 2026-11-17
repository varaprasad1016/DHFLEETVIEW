"""maintenance planner: schedules and inspection records

Revision ID: 0018_maintenance
Revises: 0017_infringement_reviews
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0018_maintenance"
down_revision = "0017_infringement_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "maintenance_schedules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("traccar_device_id", sa.BigInteger, nullable=False),
        sa.Column("registration", sa.String(20)),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("interval_value", sa.Integer, nullable=False),
        sa.Column("interval_unit", sa.String(8), nullable=False),
        sa.Column("next_due", sa.Date),
        sa.Column("active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("updated_by", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_maintenance_schedules_traccar_device_id", "maintenance_schedules", ["traccar_device_id"])
    op.create_table(
        "maintenance_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("traccar_device_id", sa.BigInteger, nullable=False),
        sa.Column("registration", sa.String(20)),
        sa.Column("schedule_id", UUID(as_uuid=True), sa.ForeignKey("maintenance_schedules.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("due_on", sa.Date),
        sa.Column("performed_on", sa.Date, nullable=False),
        sa.Column("performed_by", sa.String(160)),
        sa.Column("odometer_km", sa.Integer),
        sa.Column("result", sa.String(24)),
        sa.Column("brake_test_type", sa.String(24)),
        sa.Column("brake_service_pct", sa.Numeric(5, 1)),
        sa.Column("brake_secondary_pct", sa.Numeric(5, 1)),
        sa.Column("brake_parking_pct", sa.Numeric(5, 1)),
        sa.Column("defects_found", sa.Text),
        sa.Column("notes", sa.Text),
        sa.Column("document_path", sa.String(500)),
        sa.Column("document_name", sa.String(200)),
        sa.Column("document_type", sa.String(60)),
        sa.Column("created_by", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_maintenance_records_traccar_device_id", "maintenance_records", ["traccar_device_id"])


def downgrade() -> None:
    op.drop_table("maintenance_records")
    op.drop_table("maintenance_schedules")

"""driver compliance records, Driver CPC courses, tachograph card expiry

Revision ID: 0019_driver_records
Revises: 0018_maintenance
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0019_driver_records"
down_revision = "0018_maintenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tacho_files", sa.Column("card_expiry", sa.Date))
    op.create_table(
        "driver_records",
        sa.Column("traccar_driver_id", sa.BigInteger, primary_key=True),
        sa.Column("licence_number", sa.String(24)),
        sa.Column("licence_categories", sa.String(80)),
        sa.Column("licence_expiry", sa.Date),
        sa.Column("licence_checked_on", sa.Date),
        sa.Column("licence_points", sa.Integer),
        sa.Column("licence_check_months", sa.Integer),
        sa.Column("dqc_expiry", sa.Date),
        sa.Column("card_expiry", sa.Date),
        sa.Column("medical_expiry", sa.Date),
        sa.Column("adr_expiry", sa.Date),
        sa.Column("notes", sa.Text),
        sa.Column("updated_by", sa.String(120)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "driver_cpc_courses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("traccar_driver_id", sa.BigInteger, nullable=False),
        sa.Column("course_date", sa.Date, nullable=False),
        sa.Column("hours", sa.Numeric(4, 1), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("provider", sa.String(160)),
        sa.Column("certificate_path", sa.String(500)),
        sa.Column("certificate_name", sa.String(200)),
        sa.Column("certificate_type", sa.String(60)),
        sa.Column("created_by", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_driver_cpc_courses_traccar_driver_id", "driver_cpc_courses", ["traccar_driver_id"])


def downgrade() -> None:
    op.drop_table("driver_cpc_courses")
    op.drop_table("driver_records")
    op.drop_column("tacho_files", "card_expiry")

"""driver shifts, photos, jobs, and shift_jobs

Revision ID: 0009_shifts_jobs
Revises: 0008_tacho_activities
Create Date: 2026-09-14

Hand-written (no autogenerate) per project policy. Mirrors app/models/shifts.py.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0009_shifts_jobs"
down_revision = "0008_tacho_activities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- shifts ---
    op.create_table(
        "shifts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("driver_id", UUID(as_uuid=True), sa.ForeignKey("drivers.id")),
        sa.Column("driver_name", sa.String(100), nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id")),
        sa.Column("vehicle_reg", sa.String(20)),
        sa.Column("status", sa.String(20), server_default=sa.text("'clocked_in'")),
        sa.Column("odometer_km", sa.Integer),
        sa.Column("fuel_level_pct", sa.Integer),
        sa.Column("adblue_level_pct", sa.Integer),
        sa.Column("odometer_out_km", sa.Integer),
        sa.Column("fuel_level_out_pct", sa.Integer),
        sa.Column("adblue_level_out_pct", sa.Integer),
        sa.Column("notes", sa.Text),
        sa.Column("clocked_in_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("break_started_at", sa.DateTime(timezone=True)),
        sa.Column("break_ended_at", sa.DateTime(timezone=True)),
        sa.Column("clocked_out_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_shifts_driver_name", "shifts", ["driver_name"])
    op.create_index("ix_shifts_status", "shifts", ["status"])
    op.create_index("ix_shifts_clocked_in_at", "shifts", ["clocked_in_at"])

    # --- shift_photos ---
    op.create_table(
        "shift_photos",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("shift_id", UUID(as_uuid=True),
                  sa.ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("photo_type", sa.String(30), nullable=False),
        sa.Column("content_type", sa.String(40), server_default=sa.text("'image/jpeg'")),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_shift_photos_shift_id", "shift_photos", ["shift_id"])

    # --- jobs ---
    op.create_table(
        "jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id")),
        sa.Column("driver_id", UUID(as_uuid=True), sa.ForeignKey("drivers.id")),
        sa.Column("driver_name", sa.String(100), nullable=False),
        sa.Column("vehicle_reg", sa.String(20)),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("pickup_location", sa.String(300)),
        sa.Column("dropoff_location", sa.String(300)),
        sa.Column("priority", sa.String(10), server_default=sa.text("'normal'")),
        sa.Column("status", sa.String(20), server_default=sa.text("'pending'")),
        sa.Column("assigned_by", sa.String(100)),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("denied_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("deny_reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_jobs_driver_name", "jobs", ["driver_name"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_assigned_at", "jobs", ["assigned_at"])

    # --- shift_jobs (links jobs to shifts when accepted) ---
    op.create_table(
        "shift_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("shift_id", UUID(as_uuid=True),
                  sa.ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_shift_jobs_shift_id", "shift_jobs", ["shift_id"])
    op.create_index("ix_shift_jobs_job_id", "shift_jobs", ["job_id"])


def downgrade() -> None:
    op.drop_table("shift_jobs")
    op.drop_table("jobs")
    op.drop_table("shift_photos")
    op.drop_table("shifts")

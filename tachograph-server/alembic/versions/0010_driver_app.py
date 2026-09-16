"""driver app: job numbers/progress + messages, walkaround phases, fuel logs, paperwork

Revision ID: 0010_driver_app
Revises: 0009_shifts_jobs
Create Date: 2026-09-16

Hand-written (no autogenerate) per project policy. Mirrors app/models/shifts.py,
app/models/walkaround.py and app/models/driver_app.py.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0010_driver_app"
down_revision = "0009_shifts_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- jobs: human job number (JOB-3601...), in-progress timestamp, schedule ---
    op.execute("CREATE SEQUENCE IF NOT EXISTS job_number_seq START 3601")
    op.add_column("jobs", sa.Column("number", sa.Integer,
                                    server_default=sa.text("nextval('job_number_seq')"), nullable=False))
    op.add_column("jobs", sa.Column("scheduled_at", sa.DateTime(timezone=True)))
    op.add_column("jobs", sa.Column("started_at", sa.DateTime(timezone=True)))
    op.create_index("ix_jobs_number", "jobs", ["number"], unique=True)

    op.create_table(
        "job_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender", sa.String(10), server_default=sa.text("'driver'")),  # driver|office
        sa.Column("author", sa.String(100)),
        sa.Column("kind", sa.String(12), server_default=sa.text("'message'")),  # message|change
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_job_messages_job_id", "job_messages", ["job_id"])

    # --- walkaround: pre-use vs end-of-day vs ad-hoc fault report, readings, shift link ---
    op.add_column("walkaround_checks", sa.Column("phase", sa.String(12), server_default=sa.text("'pre_use'")))
    op.add_column("walkaround_checks", sa.Column("fuel_level", sa.String(8)))
    op.add_column("walkaround_checks", sa.Column("adblue_level", sa.String(8)))
    op.add_column("walkaround_checks", sa.Column("duration_seconds", sa.Integer))
    op.add_column("walkaround_checks", sa.Column(
        "shift_id", UUID(as_uuid=True), sa.ForeignKey("shifts.id", ondelete="SET NULL")))

    op.create_table(
        "fuel_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("vehicle_reg", sa.String(20), nullable=False),
        sa.Column("driver_name", sa.String(100)),
        sa.Column("shift_id", UUID(as_uuid=True), sa.ForeignKey("shifts.id", ondelete="SET NULL")),
        sa.Column("fuel_type", sa.String(10), server_default=sa.text("'diesel'")),  # diesel|adblue|petrol|electric
        sa.Column("litres", sa.Numeric(8, 2)),
        sa.Column("cost", sa.Numeric(10, 2)),
        sa.Column("odometer_km", sa.Integer),
        sa.Column("full_tank", sa.Boolean, server_default=sa.text("true")),
        sa.Column("location", sa.String(200)),
        sa.Column("receipt_path", sa.String(500)),
        sa.Column("content_type", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_fuel_logs_vehicle_reg", "fuel_logs", ["vehicle_reg"])

    op.create_table(
        "driver_paperwork",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("vehicle_reg", sa.String(20)),
        sa.Column("driver_name", sa.String(100)),
        sa.Column("shift_id", UUID(as_uuid=True), sa.ForeignKey("shifts.id", ondelete="SET NULL")),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(12), server_default=sa.text("'other'")),  # job_sheet|pod|receipt|other
        sa.Column("note", sa.Text),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("content_type", sa.String(60)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_driver_paperwork_driver_name", "driver_paperwork", ["driver_name"])


def downgrade() -> None:
    op.drop_table("driver_paperwork")
    op.drop_table("fuel_logs")
    for col in ("shift_id", "duration_seconds", "adblue_level", "fuel_level", "phase"):
        op.drop_column("walkaround_checks", col)
    op.drop_table("job_messages")
    op.drop_index("ix_jobs_number", table_name="jobs")
    for col in ("started_at", "scheduled_at", "number"):
        op.drop_column("jobs", col)
    op.execute("DROP SEQUENCE IF EXISTS job_number_seq")

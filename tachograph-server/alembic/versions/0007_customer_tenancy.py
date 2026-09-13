"""customer tenancy and vehicle-unit ownership

Revision ID: 0007_customer_tenancy
Revises: 0006_walkaround_media
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0007_customer_tenancy"
down_revision = "0006_walkaround_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("account_code", sa.String(40), unique=True),
        sa.Column("active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "vehicles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("registration", sa.String(20), nullable=False),
        sa.Column("vin", sa.String(17)),
        sa.Column("tachograph_serial", sa.String(50)),
        sa.Column("fmc650_imei", sa.String(15)),
        sa.Column("active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "registration", name="uq_vehicle_company_registration"),
    )
    op.add_column("devices", sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id")))
    op.add_column("devices", sa.Column("vehicle_id", UUID(as_uuid=True), sa.ForeignKey("vehicles.id")))
    op.add_column("company_cards", sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id")))
    op.add_column("tba_instances", sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id")))
    op.add_column("tba_instances", sa.Column("name", sa.String(100)))
    op.add_column("tba_instances", sa.Column("ws_url", sa.String(500)))
    op.create_table(
        "driver_companies",
        sa.Column("driver_id", UUID(as_uuid=True), sa.ForeignKey("drivers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
    )
    op.add_column("schedules", sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id")))
    op.add_column("files", sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id")))
    op.add_column("tacho_files", sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id")))
    op.add_column("tacho_files", sa.Column("vehicle_id", UUID(as_uuid=True), sa.ForeignKey("vehicles.id")))
    op.add_column("tacho_files", sa.Column("source_device_id", UUID(as_uuid=True), sa.ForeignKey("devices.id")))
    op.add_column("infringements", sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id")))
    op.add_column("vehicle_status", sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id")))
    op.create_index("ix_tacho_files_company", "tacho_files", ["company_id"])
    op.create_index("ix_tacho_files_vehicle_id", "tacho_files", ["vehicle_id"])
    op.create_index("ix_infringements_company", "infringements", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_infringements_company", table_name="infringements")
    op.drop_index("ix_tacho_files_vehicle_id", table_name="tacho_files")
    op.drop_index("ix_tacho_files_company", table_name="tacho_files")
    op.drop_column("vehicle_status", "company_id")
    op.drop_column("infringements", "company_id")
    op.drop_column("tacho_files", "source_device_id")
    op.drop_column("tacho_files", "vehicle_id")
    op.drop_column("tacho_files", "company_id")
    op.drop_column("files", "company_id")
    op.drop_column("schedules", "company_id")
    op.drop_table("driver_companies")
    op.drop_column("tba_instances", "ws_url")
    op.drop_column("tba_instances", "name")
    op.drop_column("tba_instances", "company_id")
    op.drop_column("company_cards", "company_id")
    op.drop_column("devices", "vehicle_id")
    op.drop_column("devices", "company_id")
    op.drop_table("vehicles")
    op.drop_table("companies")

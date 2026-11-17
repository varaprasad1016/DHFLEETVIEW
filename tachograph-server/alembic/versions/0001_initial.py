"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-06

Hand-written (no autogenerate) per project policy. Mirrors app/models/*.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
GEN_UUID = sa.text("gen_random_uuid()")
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column("imei", sa.String(15), nullable=False, unique=True),
        sa.Column("vehicle_reg", sa.String(20)),
        sa.Column("vin", sa.String(17)),
        sa.Column("model", sa.String(20)),
        sa.Column("firmware_version", sa.String(30)),
        sa.Column("tacho_type", sa.String(50)),
        sa.Column("protocol_path", sa.String(2)),
        sa.Column("last_seen", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
    )

    op.create_table(
        "drivers",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column("name", sa.String(100)),
        sa.Column("card_number", sa.String(20), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
    )

    op.create_table(
        "company_cards",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column("card_id", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(100)),
        sa.Column("number", sa.String(20)),
        sa.Column("active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
    )

    op.create_table(
        "tba_instances",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column("tba_id", sa.String(50), nullable=False, unique=True),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True)),
        sa.Column("connected", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
    )

    op.create_table(
        "webhooks",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("secret", sa.String(100), nullable=False),
        sa.Column("events", pg.JSONB, nullable=False),
        sa.Column("active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
    )

    op.create_table(
        "sftp_clients",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer, server_default=sa.text("22")),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("password_encrypted", sa.Text),
        sa.Column("private_key_encrypted", sa.Text),
        sa.Column("base_path", sa.String(255), server_default=sa.text("'/'")),
        sa.Column("client_code", sa.String(20)),
        sa.Column("active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
    )

    op.create_table(
        "driver_assignments",
        sa.Column("driver_id", UUID, sa.ForeignKey("drivers.id"), primary_key=True),
        sa.Column("device_id", UUID, sa.ForeignKey("devices.id"), primary_key=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("unassigned_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "schedules",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column("device_id", UUID, sa.ForeignKey("devices.id")),
        sa.Column("driver_id", UUID, sa.ForeignKey("drivers.id")),
        sa.Column("card_id", UUID, sa.ForeignKey("company_cards.id")),
        sa.Column("file_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'pending'")),
        sa.Column("triggered_by", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text),
    )

    op.create_table(
        "files",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column("device_id", UUID, sa.ForeignKey("devices.id")),
        sa.Column("driver_id", UUID, sa.ForeignKey("drivers.id")),
        sa.Column("file_type", sa.String(30), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("format", sa.String(5)),
        sa.Column("size_bytes", sa.Integer),
        sa.Column("sha256", sa.String(64)),
        sa.Column("storage_key", sa.String(500)),
        sa.Column("downloaded_at", sa.DateTime(timezone=True)),
        sa.Column("sftp_status", sa.String(10), server_default=sa.text("'pending'")),
        sa.Column("sftp_pushed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
    )

    op.create_table(
        "compliance_state",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column("entity_type", sa.String(10), nullable=False),
        sa.Column("entity_id", UUID, nullable=False),
        sa.Column("last_download_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), server_default=sa.text("'compliant'")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW),
        sa.UniqueConstraint("entity_type", "entity_id", name="uq_compliance_entity"),
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column("webhook_id", UUID, sa.ForeignKey("webhooks.id")),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", pg.JSONB, nullable=False),
        sa.Column("status", sa.String(10), server_default=sa.text("'pending'")),
        sa.Column("attempts", sa.Integer, server_default=sa.text("0")),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
    )

    op.create_table(
        "card_events",
        sa.Column("id", UUID, primary_key=True, server_default=GEN_UUID),
        sa.Column("tba_id", UUID, sa.ForeignKey("tba_instances.id")),
        sa.Column("card_id", UUID, sa.ForeignKey("company_cards.id")),
        sa.Column("device_id", UUID, sa.ForeignKey("devices.id")),
        sa.Column("schedule_id", UUID, sa.ForeignKey("schedules.id")),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("details", pg.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW),
    )

    op.create_index("ix_files_device_id", "files", ["device_id"])
    op.create_index("ix_schedules_status", "schedules", ["status"])
    op.create_index("ix_card_events_created_at", "card_events", ["created_at"])


def downgrade() -> None:
    for table in (
        "card_events",
        "webhook_deliveries",
        "compliance_state",
        "files",
        "schedules",
        "driver_assignments",
        "sftp_clients",
        "webhooks",
        "tba_instances",
        "company_cards",
        "drivers",
        "devices",
    ):
        op.drop_table(table)

"""tacho files archive and infringements

Revision ID: 0004_tacho_compliance
Revises: 0003_walkaround
Create Date: 2026-09-08

Hand-written (no autogenerate) per project policy. Mirrors app/models/tacho.py.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0004_tacho_compliance"
down_revision = "0003_walkaround"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tacho_files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("file_kind", sa.String(16), server_default=sa.text("'unknown'")),
        sa.Column("driver_ref", sa.String(40)),
        sa.Column("vehicle_ref", sa.String(20)),
        sa.Column("size_bytes", sa.Integer),
        sa.Column("sha256", sa.String(64)),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("source", sa.String(12), server_default=sa.text("'upload'")),
        sa.Column("parsed", sa.Boolean, server_default=sa.text("false")),
        sa.Column("parse_error", sa.Text),
        sa.Column("retain_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tacho_files_driver", "tacho_files", ["driver_ref"])
    op.create_index("ix_tacho_files_vehicle", "tacho_files", ["vehicle_ref"])

    op.create_table(
        "infringements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("driver_ref", sa.String(40), nullable=False),
        sa.Column("rule", sa.String(40), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("severity", sa.String(14), server_default=sa.text("'serious'")),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail", sa.Text),
        sa.Column("limit_minutes", sa.Integer),
        sa.Column("actual_minutes", sa.Integer),
        sa.Column("source_file_id", UUID(as_uuid=True),
                  sa.ForeignKey("tacho_files.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(14), server_default=sa.text("'open'")),
        sa.Column("dedup_key", sa.String(80), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_infringements_driver", "infringements", ["driver_ref"])
    op.create_index("ix_infringements_status", "infringements", ["status"])


def downgrade() -> None:
    op.drop_table("infringements")
    op.drop_table("tacho_files")

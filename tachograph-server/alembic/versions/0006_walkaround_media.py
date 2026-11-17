"""walkaround photos + driver signature

Revision ID: 0006_walkaround_media
Revises: 0005_vehicle_status
Create Date: 2026-09-08

Hand-written (no autogenerate) per project policy.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0006_walkaround_media"
down_revision = "0005_vehicle_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("walkaround_checks", sa.Column("signature_path", sa.String(500)))
    op.create_table(
        "walkaround_photos",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("check_id", UUID(as_uuid=True),
                  sa.ForeignKey("walkaround_checks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item", sa.String(80)),
        sa.Column("content_type", sa.String(40), server_default=sa.text("'image/jpeg'")),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_walkaround_photos_check", "walkaround_photos", ["check_id"])


def downgrade() -> None:
    op.drop_table("walkaround_photos")
    op.drop_column("walkaround_checks", "signature_path")

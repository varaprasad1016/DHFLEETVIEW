"""monthly licence state

Revision ID: 0002_license_state
Revises: 0001_initial
Create Date: 2026-09-07

Hand-written (no autogenerate) per project policy. Mirrors app/models/licensing.py.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_license_state"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "license_state",
        sa.Column("server_id", sa.String(64), primary_key=True),
        sa.Column("public_key", sa.String(256)),
        sa.Column("paired_at", sa.DateTime(timezone=True)),
        sa.Column("period", sa.String(7)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("license_state")

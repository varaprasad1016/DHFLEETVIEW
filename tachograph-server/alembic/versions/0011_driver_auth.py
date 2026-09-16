"""driver accounts (name + PIN) and driver app sessions

Revision ID: 0011_driver_auth
Revises: 0010_driver_app
Create Date: 2026-09-16

Hand-written (no autogenerate) per project policy. Mirrors app/models/driver_auth.py.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0011_driver_auth"
down_revision = "0010_driver_app"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "driver_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(30)),
        sa.Column("pin_hash", sa.String(200), nullable=False),
        sa.Column("active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("failed_attempts", sa.Integer, server_default=sa.text("0")),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute("CREATE UNIQUE INDEX ux_driver_accounts_lower_name ON driver_accounts (lower(name))")

    op.create_table(
        "driver_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID(as_uuid=True),
                  sa.ForeignKey("driver_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_agent", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_driver_sessions_account_id", "driver_sessions", ["account_id"])


def downgrade() -> None:
    op.drop_table("driver_sessions")
    op.execute("DROP INDEX IF EXISTS ux_driver_accounts_lower_name")
    op.drop_table("driver_accounts")

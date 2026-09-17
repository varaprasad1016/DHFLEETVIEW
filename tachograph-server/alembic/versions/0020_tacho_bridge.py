"""Tacho Bridge App sign-ins and the apps, company cards and card racks seen on them

Revision ID: 0020_tacho_bridge
Revises: 0019_driver_records
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0020_tacho_bridge"
down_revision = "0019_driver_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bridge_credentials",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_user_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("owner_name", sa.String(160)),
        sa.Column("label", sa.String(80)),
        sa.Column("username", sa.String(40), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("created_by", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "bridge_nodes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_user_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("credential_id", UUID(as_uuid=True)),
        sa.Column("online", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("info", JSONB),
        sa.Column("remote_addr", sa.String(64)),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("owner_user_id", "kind", "key", name="uq_bridge_nodes_owner_kind_key"),
    )


def downgrade() -> None:
    op.drop_table("bridge_nodes")
    op.drop_table("bridge_credentials")

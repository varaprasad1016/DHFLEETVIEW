"""who reached the site, from where, on what

Revision ID: 0032_site_access
Revises: 0031_operators
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_site_access"
down_revision = "0031_operators"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_access",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("day", sa.Date(), nullable=False, index=True),
        sa.Column("address", sa.String(45), nullable=False, index=True),
        sa.Column("agent", sa.String(400), nullable=False),
        sa.Column("agent_hash", sa.String(32), nullable=False),
        sa.Column("device", sa.String(40), nullable=False),
        sa.Column("browser", sa.String(40), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("app_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sign_ins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("refused", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used", sa.String(120)),
        sa.Column("account", sa.String(200), index=True),
        sa.Column("robot", sa.Boolean(), nullable=False, server_default=sa.text("false"), index=True),
        sa.UniqueConstraint("day", "address", "agent_hash", name="uq_site_access_day_address_agent"),
    )
    op.create_table(
        "site_access_cursor",
        sa.Column("path", sa.String(300), primary_key=True),
        sa.Column("offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("site_access_cursor")
    op.drop_table("site_access")

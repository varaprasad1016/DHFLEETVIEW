"""a TachoSync key per customer, so each one's files come to their own vehicles

Revision ID: 0033_company_tachosync_key
Revises: 0032_site_access
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_company_tachosync_key"
down_revision = "0032_site_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("tachosync_api_key", sa.String(200)))
    op.add_column("companies", sa.Column("tachosync_checked_at", sa.DateTime(timezone=True)))
    op.add_column("companies", sa.Column("tachosync_status", sa.String(200)))


def downgrade() -> None:
    op.drop_column("companies", "tachosync_status")
    op.drop_column("companies", "tachosync_checked_at")
    op.drop_column("companies", "tachosync_api_key")

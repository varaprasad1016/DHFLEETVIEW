"""remember which spans were crewed, because crewed work is rested differently

Multi-manned work gets 9 hours of daily rest inside 30 rather than 11 inside
24. The parsers can tell - the card sat in the second slot - but until now the
span was stored without it, so anything re-analysed from the database judged a
perfectly legal two-up shift against the single-driver limit.

Revision ID: 0034_activity_crew
Revises: 0033_company_tachosync_key
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034_activity_crew"
down_revision = "0033_company_tachosync_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tacho_activities", sa.Column(
        "crew", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("tacho_activities", "crew")

"""Persist the company/operator name from vehicle-unit overview files."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_tacho_company_name"
down_revision = "0006_walkaround_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tacho_files", sa.Column("company_name", sa.String(128)))


def downgrade() -> None:
    op.drop_column("tacho_files", "company_name")

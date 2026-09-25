"""the data levels at which a SIM warns and is cut off

Revision ID: 0026_sim_levels
Revises: 0025_sim_cards
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_sim_levels"
down_revision = "0025_sim_cards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sim_cards", sa.Column("warning_mb", sa.Float))
    op.add_column("sim_cards", sa.Column("limit_mb", sa.Float))


def downgrade() -> None:
    op.drop_column("sim_cards", "limit_mb")
    op.drop_column("sim_cards", "warning_mb")

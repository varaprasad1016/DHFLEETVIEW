"""what the network last said about a SIM, and when it was activated

Revision ID: 0030_sim_activation
Revises: 0029_send_once_per_address
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_sim_activation"
down_revision = "0029_send_once_per_address"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `status` already holds what the exported spreadsheet said at import time.
    # This is different: what the network itself answered, and when we asked.
    op.add_column("sim_cards", sa.Column("live_status", sa.String(32)))
    op.add_column("sim_cards", sa.Column("checked_at", sa.DateTime(timezone=True)))
    op.add_column("sim_cards", sa.Column("activated_at", sa.DateTime(timezone=True)))
    op.add_column("sim_cards", sa.Column("activated_by", sa.String(120)))


def downgrade() -> None:
    op.drop_column("sim_cards", "activated_by")
    op.drop_column("sim_cards", "activated_at")
    op.drop_column("sim_cards", "checked_at")
    op.drop_column("sim_cards", "live_status")

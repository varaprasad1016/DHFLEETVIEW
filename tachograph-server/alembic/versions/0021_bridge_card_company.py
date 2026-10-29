"""a company card belongs to one DH FleetView account, whose files it may download

Revision ID: 0021_bridge_card_company
Revises: 0020_tacho_bridge
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_bridge_card_company"
down_revision = "0020_tacho_bridge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bridge_nodes", sa.Column("assigned_user_id", sa.BigInteger))
    op.add_column("bridge_nodes", sa.Column("assigned_name", sa.String(160)))
    op.create_index("ix_bridge_nodes_assigned_user_id", "bridge_nodes", ["assigned_user_id"])


def downgrade() -> None:
    op.drop_index("ix_bridge_nodes_assigned_user_id", table_name="bridge_nodes")
    op.drop_column("bridge_nodes", "assigned_name")
    op.drop_column("bridge_nodes", "assigned_user_id")

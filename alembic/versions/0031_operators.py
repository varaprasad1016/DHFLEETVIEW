"""who operates each vehicle, as distinct from who is billed

Revision ID: 0031_operators
Revises: 0030_sim_activation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_operators"
down_revision = "0030_sim_activation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operators",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("match_key", sa.String(160), nullable=False, unique=True),
        sa.Column("contact_email", sa.String(200)),
        sa.Column("source", sa.String(16), nullable=False, server_default="download"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # Nullable on both: a vehicle fitted before its first download has no
    # operator yet, and a driver-card file never carries one.
    op.add_column("vehicles", sa.Column(
        "operator_id", sa.dialects.postgresql.UUID(as_uuid=True),
        sa.ForeignKey("operators.id", ondelete="SET NULL")))
    op.add_column("tacho_files", sa.Column(
        "operator_id", sa.dialects.postgresql.UUID(as_uuid=True),
        sa.ForeignKey("operators.id", ondelete="SET NULL")))
    op.create_index("ix_vehicles_operator", "vehicles", ["operator_id"])
    op.create_index("ix_tacho_files_operator", "tacho_files", ["operator_id"])


def downgrade() -> None:
    op.drop_index("ix_tacho_files_operator", table_name="tacho_files")
    op.drop_index("ix_vehicles_operator", table_name="vehicles")
    op.drop_column("tacho_files", "operator_id")
    op.drop_column("vehicles", "operator_id")
    op.drop_table("operators")

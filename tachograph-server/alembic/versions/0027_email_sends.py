"""what the platform has emailed by itself, and when

Revision ID: 0027_email_sends
Revises: 0026_sim_levels
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_email_sends"
down_revision = "0026_sim_levels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_sends",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False, index=True),
        sa.Column("period_key", sa.String(32), nullable=False, index=True),
        sa.Column("reference", sa.String(64)),
        sa.Column("user_id", sa.BigInteger, index=True),
        sa.Column("account_name", sa.String(200)),
        sa.Column("recipient", sa.String(200), nullable=False),
        sa.Column("subject", sa.String(300)),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("detail", sa.Text),
        sa.Column("automatic", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # One automatic send of one thing for one period, and no more. A failed
    # attempt is deliberately outside this, so a retry is allowed to happen.
    op.create_index("ix_email_sends_once", "email_sends",
                    ["kind", "period_key", "reference"], unique=True,
                    postgresql_where=sa.text("automatic AND status = 'sent'"))
    op.create_index("ix_email_sends_recent", "email_sends", ["sent_at"])


def downgrade() -> None:
    op.drop_index("ix_email_sends_recent", table_name="email_sends")
    op.drop_index("ix_email_sends_once", table_name="email_sends")
    op.drop_table("email_sends")

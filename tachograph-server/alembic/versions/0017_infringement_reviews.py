"""driver sign-off and office debrief for infringements

Revision ID: 0017_infringement_reviews
Revises: 0016_tacho_live
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0017_infringement_reviews"
down_revision = "0016_tacho_live"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "infringement_reviews",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("infringement_id", UUID(as_uuid=True), sa.ForeignKey("infringements.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("driver_account_id", UUID(as_uuid=True), sa.ForeignKey("driver_accounts.id", ondelete="SET NULL")),
        sa.Column("driver_name", sa.String(120)),
        sa.Column("driver_signed_at", sa.DateTime(timezone=True)),
        sa.Column("driver_signature_path", sa.String(500)),
        sa.Column("driver_comment", sa.Text),
        sa.Column("debriefed_at", sa.DateTime(timezone=True)),
        sa.Column("debriefed_by", sa.String(120)),
        sa.Column("debrief_action", sa.String(40)),
        sa.Column("debrief_notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("infringement_reviews")

"""one rate per package, rather than one per part fitted

A vehicle is charged for the package it is on - live view, or tacho tracking
with live view - not for a list of parts added together. So the three
component rates give way to two package rates.

The old columns held only the figures used while the module was being built,
and every invoice raised from them has been deleted, so nothing is carried
across: an account with no package rate of its own falls back to the standard
rates, which is where these customers should start.

Revision ID: 0028_rate_packages
Revises: 0027_email_sends
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_rate_packages"
down_revision = "0027_email_sends"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("billing_accounts", sa.Column("rate_live", sa.Numeric(10, 2)))
    op.add_column("billing_accounts", sa.Column("rate_tacho", sa.Numeric(10, 2)))
    op.drop_column("billing_accounts", "rate_tracking")
    op.drop_column("billing_accounts", "rate_camera")
    op.drop_column("billing_accounts", "rate_tachograph")


def downgrade() -> None:
    op.add_column("billing_accounts", sa.Column("rate_tracking", sa.Numeric(10, 2)))
    op.add_column("billing_accounts", sa.Column("rate_camera", sa.Numeric(10, 2)))
    op.add_column("billing_accounts", sa.Column("rate_tachograph", sa.Numeric(10, 2)))
    op.drop_column("billing_accounts", "rate_tacho")
    op.drop_column("billing_accounts", "rate_live")

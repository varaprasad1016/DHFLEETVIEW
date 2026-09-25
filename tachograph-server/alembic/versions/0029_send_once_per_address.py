"""one automatic send of one thing to one address

The index this replaces allowed one automatic send of a thing per period, full
stop - which was right while only invoices used it, each going to a single
customer. The account watch emails the same alarm to several addresses at once,
and the second one was rejected as a duplicate.

Adding the recipient makes the rule what it was always meant to be: the same
thing is not sent to the same person twice by itself. Billing a customer twice
is prevented separately and more strictly - a sent invoice is never picked up
by a run again.

Revision ID: 0029_send_once_per_address
Revises: 0028_rate_packages
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_send_once_per_address"
down_revision = "0028_rate_packages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_email_sends_once", table_name="email_sends")
    op.create_index("ix_email_sends_once", "email_sends",
                    ["kind", "period_key", "reference", "recipient"], unique=True,
                    postgresql_where=sa.text("automatic AND status = 'sent'"))


def downgrade() -> None:
    op.drop_index("ix_email_sends_once", table_name="email_sends")
    op.create_index("ix_email_sends_once", "email_sends",
                    ["kind", "period_key", "reference"], unique=True,
                    postgresql_where=sa.text("automatic AND status = 'sent'"))

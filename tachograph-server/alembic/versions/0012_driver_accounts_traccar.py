"""link driver accounts to DH FleetView (Traccar) drivers

Revision ID: 0012_driver_accounts_traccar
Revises: 0011_driver_auth
Create Date: 2026-09-16

Drivers are now created on the DH FleetView Drivers page; the account here
holds only the app PIN and sessions. Names are no longer unique (Traccar does
not enforce it) — the Traccar driver identifier is.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_driver_accounts_traccar"
down_revision = "0011_driver_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("driver_accounts", sa.Column("traccar_driver_id", sa.BigInteger))
    op.add_column("driver_accounts", sa.Column("unique_id", sa.String(128)))
    op.create_index("ux_driver_accounts_traccar_driver_id", "driver_accounts", ["traccar_driver_id"], unique=True)
    op.execute("DROP INDEX IF EXISTS ux_driver_accounts_lower_name")
    op.execute("CREATE INDEX ix_driver_accounts_lower_name ON driver_accounts (lower(name))")
    op.execute("CREATE INDEX ix_driver_accounts_lower_unique_id ON driver_accounts (lower(unique_id))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_driver_accounts_lower_unique_id")
    op.execute("DROP INDEX IF EXISTS ix_driver_accounts_lower_name")
    op.execute("CREATE UNIQUE INDEX ux_driver_accounts_lower_name ON driver_accounts (lower(name))")
    op.drop_index("ux_driver_accounts_traccar_driver_id", table_name="driver_accounts")
    op.drop_column("driver_accounts", "unique_id")
    op.drop_column("driver_accounts", "traccar_driver_id")

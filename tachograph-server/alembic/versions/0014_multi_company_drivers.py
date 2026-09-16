"""one driver login across companies; company tag on driver records; card numbers

Revision ID: 0014_multi_company_drivers
Revises: 0013_app_settings

A driver (person) has one login (driver_accounts, unique by identifier) and a
membership per company: each company's DH FleetView driver record
(traccar_driver_id). Shifts, jobs, walkarounds, fuel and paperwork record the
company driver record they belong to, so each company only sees its own.
tacho_files.card_number lets a driver see their own tachograph data.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0014_multi_company_drivers"
down_revision = "0013_app_settings"
branch_labels = None
depends_on = None

RECORD_TABLES = ("jobs", "shifts", "walkaround_checks", "fuel_logs", "driver_paperwork")


def upgrade() -> None:
    op.create_table(
        "driver_memberships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID(as_uuid=True), sa.ForeignKey("driver_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("traccar_driver_id", sa.BigInteger, nullable=False, unique=True),
        sa.Column("company_label", sa.String(160)),
        sa.Column("owner_user_id", sa.BigInteger),
        sa.Column("active", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_driver_memberships_account_id", "driver_memberships", ["account_id"])

    # Existing accounts linked to a DH FleetView driver become that company's membership.
    op.execute("""
        INSERT INTO driver_memberships (account_id, traccar_driver_id, company_label, active)
        SELECT id, traccar_driver_id, created_by, active FROM driver_accounts WHERE traccar_driver_id IS NOT NULL
    """)
    op.execute("CREATE UNIQUE INDEX ux_driver_accounts_lower_unique_id ON driver_accounts (lower(unique_id)) WHERE unique_id IS NOT NULL")

    for table in RECORD_TABLES:
        op.add_column(table, sa.Column("traccar_driver_id", sa.BigInteger))
        op.create_index(f"ix_{table}_traccar_driver_id", table, ["traccar_driver_id"])
        # Tag existing records whose driver name belongs to exactly one company driver.
        op.execute(f"""
            UPDATE {table} r SET traccar_driver_id = m.traccar_driver_id
            FROM driver_accounts a JOIN driver_memberships m ON m.account_id = a.id
            WHERE lower(r.driver_name) = lower(a.name)
              AND r.traccar_driver_id IS NULL
              AND (SELECT count(*) FROM driver_memberships m2 WHERE m2.account_id = a.id) = 1
        """)

    op.add_column("tacho_files", sa.Column("card_number", sa.String(32)))
    op.create_index("ix_tacho_files_card_number", "tacho_files", ["card_number"])


def downgrade() -> None:
    op.drop_index("ix_tacho_files_card_number", table_name="tacho_files")
    op.drop_column("tacho_files", "card_number")
    for table in RECORD_TABLES:
        op.drop_index(f"ix_{table}_traccar_driver_id", table_name=table)
        op.drop_column(table, "traccar_driver_id")
    op.execute("DROP INDEX IF EXISTS ux_driver_accounts_lower_unique_id")
    op.drop_table("driver_memberships")

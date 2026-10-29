"""join the two migration branches; record who uploaded each tacho file

0007_tacho_company_name and 0007_customer_tenancy both followed
0006_walkaround_media, which left two heads (so `alembic upgrade head` failed).
This revision merges them. It also stores the DH FleetView user who uploaded a
tacho file, so each company only sees its own tachograph data.

Revision ID: 0015_tacho_file_uploader
Revises: 0014_multi_company_drivers, 0007_tacho_company_name
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_tacho_file_uploader"
down_revision = ("0014_multi_company_drivers", "0007_tacho_company_name")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tacho_files", sa.Column("uploaded_by_user_id", sa.BigInteger))
    op.create_index("ix_tacho_files_uploaded_by_user_id", "tacho_files", ["uploaded_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_tacho_files_uploaded_by_user_id", table_name="tacho_files")
    op.drop_column("tacho_files", "uploaded_by_user_id")

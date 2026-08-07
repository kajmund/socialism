"""Add mode column on reports (full | quick).

Revision ID: 014_report_mode
Revises: 013_catalog_per_configuration
Create Date: 2026-08-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_report_mode"
down_revision: Union[str, Sequence[str], None] = "013_catalog_per_configuration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="full"),
    )


def downgrade() -> None:
    op.drop_column("reports", "mode")

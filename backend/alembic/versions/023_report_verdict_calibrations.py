"""report_verdict_calibrations — operator judgment per report.

Revision ID: 023_report_verdict_calibrations
Revises: 022_configuration_report_thresholds
Create Date: 2026-08-11
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "023_report_verdict_calibrations"
down_revision: Union[str, Sequence[str], None] = "022_configuration_report_thresholds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "report_verdict_calibrations",
        sa.Column("report_id", sa.String(length=64), nullable=False),
        sa.Column("matches", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("report_id"),
    )


def downgrade() -> None:
    op.drop_table("report_verdict_calibrations")

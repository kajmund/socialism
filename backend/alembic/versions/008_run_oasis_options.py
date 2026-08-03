"""Add oasis_options JSON column on runs.

Revision ID: 008_run_oasis_options
Revises: 007_reports
Create Date: 2026-08-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_run_oasis_options"
down_revision: Union[str, Sequence[str], None] = "007_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "oasis_options",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("runs", "oasis_options")

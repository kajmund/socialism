"""live_progress columns on runs for realtime activity catch-up.

Revision ID: 029_run_live_progress
Revises: 028_spindoctor_widgets
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "029_run_live_progress"
down_revision: Union[str, Sequence[str], None] = "028_spindoctor_widgets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("live_progress_main", sa.JSON(), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("live_progress_a", sa.JSON(), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("live_progress_b", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("runs", "live_progress_b")
    op.drop_column("runs", "live_progress_a")
    op.drop_column("runs", "live_progress_main")

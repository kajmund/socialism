"""Add Word application claim fields and rename posted → applied.

Revision ID: 068_word_application_lifecycle
Revises: 067_researchplan_valid_proposals
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "068_word_application_lifecycle"
down_revision: Union[str, Sequence[str], None] = "067_researchplan_valid_proposals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "expertgranskning_results",
        sa.Column("application_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "expertgranskning_results",
        sa.Column("application_error", sa.String(length=64), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE expertgranskning_results "
            "SET status = 'applied' "
            "WHERE status = 'posted'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE expertgranskning_results "
            "SET status = 'posted' "
            "WHERE status = 'applied'"
        )
    )
    op.drop_column("expertgranskning_results", "application_error")
    op.drop_column("expertgranskning_results", "application_id")

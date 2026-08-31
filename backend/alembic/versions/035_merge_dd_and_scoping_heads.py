"""Merge parallel Alembic heads (dd_candidate_runs + project scoping).

Revision ID: 035_merge_dd_and_scoping_heads
Revises: 033_dd_candidate_runs, 034_project_scoping_and_dd_customer
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "035_merge_dd_and_scoping_heads"
down_revision: Union[str, Sequence[str], None] = (
    "033_dd_candidate_runs",
    "034_project_scoping_and_dd_customer",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

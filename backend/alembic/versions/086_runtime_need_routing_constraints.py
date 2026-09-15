"""Persist routing constraints on research_runtime_needs.

Revision ID: 086_runtime_need_routing_constraints
Revises: 085_research_loop_user_prompts
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "086_runtime_need_routing_constraints"
down_revision: Union[str, Sequence[str], None] = "085_research_loop_user_prompts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "research_runtime_needs",
        sa.Column("domains", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "research_runtime_needs",
        sa.Column("modalities", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "research_runtime_needs",
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("research_runtime_needs", "capabilities")
    op.drop_column("research_runtime_needs", "modalities")
    op.drop_column("research_runtime_needs", "domains")

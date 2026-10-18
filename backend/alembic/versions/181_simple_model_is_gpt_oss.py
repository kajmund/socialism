"""Point the simple LLM role at gpt-oss-120b.

Revision ID: 181_simple_model_is_gpt_oss
Revises: 180_workspace_prompt_split
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "181_simple_model_is_gpt_oss"
down_revision: str | Sequence[str] | None = "180_workspace_prompt_split"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE llm_configurations "
            "SET selection_role = 'fast', "
            "priority = CASE WHEN priority >= 100 THEN 10 ELSE priority END "
            "WHERE profile_id = 'gpt-oss-120b'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE llm_configurations "
            "SET selection_role = 'balanced', priority = 100 "
            "WHERE profile_id = 'gpt-oss-120b' AND selection_role = 'fast' AND priority = 10"
        )
    )

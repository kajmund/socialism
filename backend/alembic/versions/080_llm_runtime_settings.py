"""Add llm_runtime_settings singleton for admin LLM picker.

Revision ID: 080_llm_runtime_settings
Revises: 079_review_output_contract_prompt
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "080_llm_runtime_settings"
down_revision: Union[str, Sequence[str], None] = "079_review_output_contract_prompt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_runtime_settings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("top_p", sa.Float(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column("reasoning_effort", sa.String(length=16), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("llm_runtime_settings")

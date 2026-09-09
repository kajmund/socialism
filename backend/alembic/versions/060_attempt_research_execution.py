"""Attempt research lifecycle: plan snapshot, evidence ordinals, original id.

Revision ID: 060_attempt_research_execution
Revises: 059_execution_domain
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "060_attempt_research_execution"
down_revision: Union[str, Sequence[str], None] = "059_execution_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("execution_attempts") as batch:
        batch.add_column(sa.Column("research_plan_snapshot", sa.JSON(), nullable=True))
    with op.batch_alter_table("evidence_set_items") as batch:
        batch.add_column(sa.Column("original_evidence_id", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0")
        )
    op.create_index(
        "ix_evidence_set_items_set_ordinal",
        "evidence_set_items",
        ["evidence_set_id", "ordinal"],
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_set_items_set_ordinal", table_name="evidence_set_items")
    with op.batch_alter_table("evidence_set_items") as batch:
        batch.drop_column("ordinal")
        batch.drop_column("original_evidence_id")
    with op.batch_alter_table("execution_attempts") as batch:
        batch.drop_column("research_plan_snapshot")

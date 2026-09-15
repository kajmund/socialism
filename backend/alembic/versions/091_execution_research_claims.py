"""Durable research claim/lease metadata.

Revision ID: 091_execution_research_claims
Revises: 090_knowledge_questions
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "091_execution_research_claims"
down_revision: Union[str, Sequence[str], None] = "090_knowledge_questions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "execution_research_claims",
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("worker_id", sa.String(length=64), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_request", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["execution_attempts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
    )
    op.create_index(
        "ix_execution_research_claims_lease_expires_at",
        "execution_research_claims",
        ["lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_execution_research_claims_lease_expires_at",
        table_name="execution_research_claims",
    )
    op.drop_table("execution_research_claims")

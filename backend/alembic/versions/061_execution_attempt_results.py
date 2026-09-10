"""Persist generic_panel output against an ExecutionAttempt.

Revision ID: 061_execution_attempt_results
Revises: 060_attempt_research_execution
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "061_execution_attempt_results"
down_revision: Union[str, Sequence[str], None] = "060_attempt_research_execution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "execution_attempt_results",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("result_type", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("panel_session_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["execution_attempts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["panel_session_id"], ["panel_sessions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", name="uq_execution_attempt_results_attempt_id"),
    )
    op.create_index(
        "ix_execution_attempt_results_attempt_id",
        "execution_attempt_results",
        ["attempt_id"],
    )
    op.create_index(
        "ix_execution_attempt_results_panel_session_id",
        "execution_attempt_results",
        ["panel_session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_execution_attempt_results_panel_session_id",
        table_name="execution_attempt_results",
    )
    op.drop_index(
        "ix_execution_attempt_results_attempt_id",
        table_name="execution_attempt_results",
    )
    op.drop_table("execution_attempt_results")

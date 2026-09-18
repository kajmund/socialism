"""Persist expert links to answered canonical questions.

Revision ID: 101_expert_knowledge_receipts
Revises: 100_research_question_outcome
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "101_expert_knowledge_receipts"
down_revision: str | Sequence[str] | None = "100_research_question_outcome"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "expert_knowledge_receipts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("expert_id", sa.String(length=64), nullable=False),
        sa.Column("knowledge_question_id", sa.String(length=64), nullable=False),
        sa.Column("research_question_id", sa.String(length=64), nullable=False),
        sa.Column("source_attempt_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_set_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("origin_kind", sa.String(length=32), nullable=False),
        sa.Column("origin_ref", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "confirmed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["expert_id"], ["personas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["knowledge_question_id"], ["knowledge_questions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["research_question_id"], ["research_questions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_attempt_id"], ["execution_attempts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_set_id"], ["evidence_sets.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "expert_id",
            "knowledge_question_id",
            "source_attempt_id",
            "role",
            name="uq_expert_knowledge_receipt_lineage",
        ),
    )
    for column in (
        "customer_id",
        "expert_id",
        "knowledge_question_id",
        "research_question_id",
        "source_attempt_id",
        "evidence_set_id",
    ):
        op.create_index(
            op.f(f"ix_expert_knowledge_receipts_{column}"),
            "expert_knowledge_receipts",
            [column],
        )


def downgrade() -> None:
    op.drop_table("expert_knowledge_receipts")

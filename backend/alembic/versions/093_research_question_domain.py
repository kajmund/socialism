"""Add specific questions and expert-owned general-question DAGs.

Revision ID: 093_research_question_domain
Revises: 092_research_progress_events
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "093_research_question_domain"
down_revision: str | Sequence[str] | None = "092_research_progress_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "specific_questions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("origin_kind", sa.String(length=32), nullable=False),
        sa.Column("origin_ref", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["run_id"], ["execution_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_specific_questions_run_id"), "specific_questions", ["run_id"])
    op.create_table(
        "research_questions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("specific_question_id", sa.String(length=64), nullable=False),
        sa.Column("knowledge_question_id", sa.String(length=64), nullable=False),
        sa.Column("runtime_need_id", sa.String(length=64), nullable=True),
        sa.Column("why_needed", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["attempt_id"], ["execution_attempts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["specific_question_id"], ["specific_questions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_question_id"], ["knowledge_questions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attempt_id",
            "specific_question_id",
            "knowledge_question_id",
            name="uq_research_questions_attempt_specific_knowledge",
        ),
    )
    op.create_index(op.f("ix_research_questions_attempt_id"), "research_questions", ["attempt_id"])
    op.create_index(
        op.f("ix_research_questions_specific_question_id"),
        "research_questions",
        ["specific_question_id"],
    )
    op.create_index(
        op.f("ix_research_questions_knowledge_question_id"),
        "research_questions",
        ["knowledge_question_id"],
    )
    op.create_table(
        "research_question_experts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("question_id", sa.String(length=64), nullable=False),
        sa.Column("expert_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["question_id"], ["research_questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_id",
            "expert_id",
            "role",
            name="uq_research_question_experts_question_expert_role",
        ),
    )
    op.create_index(
        op.f("ix_research_question_experts_question_id"),
        "research_question_experts",
        ["question_id"],
    )
    op.create_index(
        op.f("ix_research_question_experts_expert_id"), "research_question_experts", ["expert_id"]
    )
    op.create_table(
        "research_question_dependencies",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("question_id", sa.String(length=64), nullable=False),
        sa.Column("depends_on_question_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["question_id"], ["research_questions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["depends_on_question_id"], ["research_questions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_id", "depends_on_question_id", name="uq_research_question_dependencies_edge"
        ),
    )
    op.create_index(
        op.f("ix_research_question_dependencies_question_id"),
        "research_question_dependencies",
        ["question_id"],
    )
    op.create_index(
        op.f("ix_research_question_dependencies_depends_on_question_id"),
        "research_question_dependencies",
        ["depends_on_question_id"],
    )


def downgrade() -> None:
    op.drop_table("research_question_dependencies")
    op.drop_table("research_question_experts")
    op.drop_table("research_questions")
    op.drop_table("specific_questions")

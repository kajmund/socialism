"""recursive research question tree

Revision ID: 124_recursive_question_tree
Revises: 668bd23eb2df
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "124_recursive_question_tree"
down_revision: str | Sequence[str] | None = "668bd23eb2df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_question_nodes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "attempt_id",
            sa.String(64),
            sa.ForeignKey("execution_attempts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "parent_question_id",
            sa.String(64),
            sa.ForeignKey("research_question_nodes.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "knowledge_question_id",
            sa.String(64),
            sa.ForeignKey("knowledge_questions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("research_need_id", sa.String(64), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_from", sa.String(32), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False, server_default="created"),
        sa.Column("atomicity", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("atomicity_noul", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("synthesis_readiness_noul", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("completeness", sa.String(32), nullable=True),
        sa.Column("completeness_noul", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_research_question_nodes_attempt_id", "research_question_nodes", ["attempt_id"])
    op.create_index(
        "ix_research_question_nodes_parent_question_id",
        "research_question_nodes",
        ["parent_question_id"],
    )
    op.create_index(
        "ix_research_question_nodes_attempt_parent",
        "research_question_nodes",
        ["attempt_id", "parent_question_id"],
    )
    op.create_index(
        "uq_research_question_nodes_root",
        "research_question_nodes",
        ["attempt_id"],
        unique=True,
        postgresql_where=sa.text("parent_question_id IS NULL"),
        sqlite_where=sa.text("parent_question_id IS NULL"),
    )
    op.create_index(
        "ix_research_question_nodes_knowledge_question_id",
        "research_question_nodes",
        ["knowledge_question_id"],
    )
    op.create_index(
        "ix_research_question_nodes_research_need_id",
        "research_question_nodes",
        ["research_need_id"],
    )

    op.create_table(
        "research_question_answers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "question_node_id",
            sa.String(64),
            sa.ForeignKey("research_question_nodes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "supersedes_answer_id",
            sa.String(64),
            sa.ForeignKey("research_question_answers.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "question_node_id",
            "version",
            name="uq_research_question_answers_node_version",
        ),
    )
    op.create_index(
        "ix_research_question_answers_question_node_id",
        "research_question_answers",
        ["question_node_id"],
    )
    with op.batch_alter_table("research_question_nodes") as batch:
        batch.add_column(sa.Column("current_answer_id", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_research_question_nodes_current_answer",
            "research_question_answers",
            ["current_answer_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_research_question_nodes_current_answer_id",
            ["current_answer_id"],
        )

    op.create_table(
        "research_answer_child_links",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "answer_id",
            sa.String(64),
            sa.ForeignKey("research_question_answers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "child_answer_id",
            sa.String(64),
            sa.ForeignKey("research_question_answers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "answer_id",
            "child_answer_id",
            name="uq_research_answer_child_links_pair",
        ),
    )
    op.create_index(
        "ix_research_answer_child_links_answer_id",
        "research_answer_child_links",
        ["answer_id"],
    )
    op.create_index(
        "ix_research_answer_child_links_child_answer_id",
        "research_answer_child_links",
        ["child_answer_id"],
    )

    op.create_table(
        "research_answer_evidence_links",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "answer_id",
            sa.String(64),
            sa.ForeignKey("research_question_answers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evidence_set_item_id",
            sa.String(64),
            sa.ForeignKey("evidence_set_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "claim_id",
            sa.String(64),
            sa.ForeignKey("research_claims.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "passage_id",
            sa.String(64),
            sa.ForeignKey("evidence_passages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "answer_id",
            "evidence_set_item_id",
            name="uq_research_answer_evidence_links_item",
        ),
    )
    for column in ("answer_id", "evidence_set_item_id", "claim_id", "passage_id"):
        op.create_index(
            f"ix_research_answer_evidence_links_{column}",
            "research_answer_evidence_links",
            [column],
        )


def downgrade() -> None:
    op.drop_table("research_answer_evidence_links")
    op.drop_table("research_answer_child_links")
    with op.batch_alter_table("research_question_nodes") as batch:
        batch.drop_index("ix_research_question_nodes_current_answer_id")
        batch.drop_constraint("fk_research_question_nodes_current_answer", type_="foreignkey")
        batch.drop_column("current_answer_id")
    op.drop_table("research_question_answers")
    op.drop_table("research_question_nodes")

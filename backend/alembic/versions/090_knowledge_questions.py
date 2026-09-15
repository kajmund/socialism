"""Persistent KnowledgeQuestion and Question→Evidence links.

Revision ID: 090_knowledge_questions
Revises: 089_evidence_quality
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "090_knowledge_questions"
down_revision: Union[str, Sequence[str], None] = "089_evidence_quality"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_questions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("identity_key", sa.String(length=64), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("display_text", sa.Text(), nullable=False),
        sa.Column("namespace", sa.String(length=64), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        sa.Column("embedding_version", sa.String(length=64), nullable=True),
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "namespace",
            "identity_key",
            name="uq_knowledge_questions_namespace_identity",
        ),
    )
    op.create_index(
        "ix_knowledge_questions_customer_id",
        "knowledge_questions",
        ["customer_id"],
    )
    op.create_table(
        "knowledge_question_evidence_links",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("question_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_ref", sa.String(length=64), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("locator", sa.String(length=512), nullable=True),
        sa.Column("source_id", sa.String(length=512), nullable=True),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("freshness", sa.String(length=16), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("source_attempt_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["knowledge_questions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_id",
            "evidence_ref",
            name="uq_knowledge_question_evidence_ref",
        ),
    )
    op.create_index(
        "ix_knowledge_question_evidence_links_question_id",
        "knowledge_question_evidence_links",
        ["question_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_question_evidence_links_question_id",
        table_name="knowledge_question_evidence_links",
    )
    op.drop_table("knowledge_question_evidence_links")
    op.drop_index(
        "ix_knowledge_questions_customer_id",
        table_name="knowledge_questions",
    )
    op.drop_table("knowledge_questions")

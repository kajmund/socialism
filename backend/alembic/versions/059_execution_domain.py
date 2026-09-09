"""Generic execution domain: execution_runs, attempts, evidence sets.

Revision ID: 059_execution_domain
Revises: 058_knowledge_documents
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "059_execution_domain"
down_revision: Union[str, Sequence[str], None] = "058_knowledge_documents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "execution_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
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
    )
    op.create_index(
        "ix_execution_runs_customer_id", "execution_runs", ["customer_id"]
    )
    op.create_index("ix_execution_runs_module", "execution_runs", ["module"])

    op.create_table(
        "evidence_sets",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("created_from_attempt_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["execution_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_sets_run_id", "evidence_sets", ["run_id"])
    op.create_index(
        "ix_evidence_sets_created_from_attempt_id",
        "evidence_sets",
        ["created_from_attempt_id"],
    )

    op.create_table(
        "execution_attempts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("parent_attempt_id", sa.String(length=64), nullable=True),
        sa.Column("attempt_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("configuration_snapshot", sa.JSON(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_set_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["execution_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["parent_attempt_id"], ["execution_attempts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_set_id"], ["evidence_sets.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_execution_attempts_run_id", "execution_attempts", ["run_id"])
    op.create_index(
        "ix_execution_attempts_parent_attempt_id",
        "execution_attempts",
        ["parent_attempt_id"],
    )
    op.create_index(
        "ix_execution_attempts_evidence_set_id",
        "execution_attempts",
        ["evidence_set_id"],
    )

    op.create_table(
        "evidence_set_items",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("evidence_set_id", sa.String(length=64), nullable=False),
        sa.Column("research_need_id", sa.String(length=64), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("locator", sa.String(length=512), nullable=True),
        sa.Column("source_id", sa.String(length=512), nullable=True),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_set_id"], ["evidence_sets.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evidence_set_items_evidence_set_id",
        "evidence_set_items",
        ["evidence_set_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evidence_set_items_evidence_set_id", table_name="evidence_set_items"
    )
    op.drop_table("evidence_set_items")
    op.drop_index(
        "ix_execution_attempts_evidence_set_id", table_name="execution_attempts"
    )
    op.drop_index(
        "ix_execution_attempts_parent_attempt_id", table_name="execution_attempts"
    )
    op.drop_index("ix_execution_attempts_run_id", table_name="execution_attempts")
    op.drop_table("execution_attempts")
    op.drop_index(
        "ix_evidence_sets_created_from_attempt_id", table_name="evidence_sets"
    )
    op.drop_index("ix_evidence_sets_run_id", table_name="evidence_sets")
    op.drop_table("evidence_sets")
    op.drop_index("ix_execution_runs_module", table_name="execution_runs")
    op.drop_index("ix_execution_runs_customer_id", table_name="execution_runs")
    op.drop_table("execution_runs")

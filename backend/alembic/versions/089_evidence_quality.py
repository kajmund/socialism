"""Persisted per-evidence quality assessments.

Revision ID: 089_evidence_quality
Revises: 088_research_completeness
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "089_evidence_quality"
down_revision: Union[str, Sequence[str], None] = "088_research_completeness"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_evidence_quality",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("evidence_set_item_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_set_id", sa.String(length=64), nullable=False),
        sa.Column("original_evidence_id", sa.String(length=64), nullable=True),
        sa.Column("scoring_policy_version", sa.String(length=32), nullable=False),
        sa.Column("authority", sa.String(length=32), nullable=False),
        sa.Column("relevance", sa.String(length=32), nullable=False),
        sa.Column("currentness", sa.String(length=32), nullable=False),
        sa.Column("source_nature", sa.String(length=32), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("independence_key", sa.String(length=1024), nullable=False),
        sa.Column("independent_source_count", sa.Integer(), nullable=False),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("declared_signals", sa.JSON(), nullable=False),
        sa.Column("model_provider", sa.String(length=64), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("model_identity_key", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["evidence_set_id"], ["evidence_sets.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_set_item_id"],
            ["evidence_set_items.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evidence_set_item_id",
            "scoring_policy_version",
            "model_identity_key",
            name="uq_research_evidence_quality_item_policy_model",
        ),
    )
    op.create_index(
        "ix_research_evidence_quality_evidence_set_item_id",
        "research_evidence_quality",
        ["evidence_set_item_id"],
    )
    op.create_index(
        "ix_research_evidence_quality_evidence_set_id",
        "research_evidence_quality",
        ["evidence_set_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_evidence_quality_evidence_set_id",
        table_name="research_evidence_quality",
    )
    op.drop_index(
        "ix_research_evidence_quality_evidence_set_item_id",
        table_name="research_evidence_quality",
    )
    op.drop_table("research_evidence_quality")

"""Entities and typed knowledge relationships.

Revision ID: 119_knowledge_entities
Revises: 118_knowledge_claim_answer_source
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "119_knowledge_entities"
down_revision: str | Sequence[str] | None = "118_knowledge_claim_answer_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_entities",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("entity_key", sa.String(length=512), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "customer_id",
            "entity_type",
            "entity_key",
            name="uq_knowledge_entities_identity",
        ),
    )
    op.create_index("ix_knowledge_entities_customer_id", "knowledge_entities", ["customer_id"])
    op.create_index("ix_knowledge_entities_type", "knowledge_entities", ["entity_type"])
    op.create_table(
        "knowledge_relationships",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("relation", sa.String(length=64), nullable=False),
        sa.Column("from_kind", sa.String(length=32), nullable=False),
        sa.Column("from_id", sa.String(length=64), nullable=False),
        sa.Column("to_kind", sa.String(length=32), nullable=False),
        sa.Column("to_id", sa.String(length=64), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "customer_id",
            "relation",
            "from_kind",
            "from_id",
            "to_kind",
            "to_id",
            name="uq_knowledge_relationships_edge",
        ),
    )
    op.create_index(
        "ix_knowledge_relationships_customer_id",
        "knowledge_relationships",
        ["customer_id"],
    )
    op.create_index(
        "ix_knowledge_relationships_from",
        "knowledge_relationships",
        ["from_kind", "from_id"],
    )
    op.create_index(
        "ix_knowledge_relationships_to",
        "knowledge_relationships",
        ["to_kind", "to_id"],
    )
    op.create_index(
        "ix_knowledge_relationships_relation",
        "knowledge_relationships",
        ["relation"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_relationships")
    op.drop_table("knowledge_entities")

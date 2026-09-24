"""Temporal claims/edges and append-only graph events.

Revision ID: 120_knowledge_graph_events
Revises: 119_knowledge_entities
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "120_knowledge_graph_events"
down_revision: str | Sequence[str] | None = "119_knowledge_entities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_claims") as batch:
        batch.add_column(sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("successor_id", sa.String(length=64), nullable=True))
        batch.create_index("ix_knowledge_claims_superseded_at", ["superseded_at"])
        batch.create_index("ix_knowledge_claims_successor_id", ["successor_id"])
        batch.create_foreign_key(
            "fk_knowledge_claims_successor_id",
            "knowledge_claims",
            ["successor_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("knowledge_relationships") as batch:
        batch.add_column(sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_index(
            "ix_knowledge_relationships_superseded_at",
            ["superseded_at"],
        )
    op.create_table(
        "knowledge_graph_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("node_kind", sa.String(length=32), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("related_id", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_graph_events_customer_id",
        "knowledge_graph_events",
        ["customer_id"],
    )
    op.create_index(
        "ix_knowledge_graph_events_customer_created",
        "knowledge_graph_events",
        ["customer_id", "created_at"],
    )
    op.create_index("ix_knowledge_graph_events_type", "knowledge_graph_events", ["event_type"])
    op.create_index(
        "ix_knowledge_graph_events_node",
        "knowledge_graph_events",
        ["node_kind", "node_id"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_graph_events")
    with op.batch_alter_table("knowledge_relationships") as batch:
        batch.drop_index("ix_knowledge_relationships_superseded_at")
        batch.drop_column("superseded_at")
        batch.drop_column("valid_to")
        batch.drop_column("valid_from")
    with op.batch_alter_table("knowledge_claims") as batch:
        batch.drop_constraint("fk_knowledge_claims_successor_id", type_="foreignkey")
        batch.drop_index("ix_knowledge_claims_successor_id")
        batch.drop_index("ix_knowledge_claims_superseded_at")
        batch.drop_column("successor_id")
        batch.drop_column("superseded_at")
        batch.drop_column("valid_to")
        batch.drop_column("valid_from")

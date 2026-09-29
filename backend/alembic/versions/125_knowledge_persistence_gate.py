"""Tight knowledge persistence: identity keys, observations, idempotent edges.

Revision ID: 125_knowledge_persistence_gate
Revises: 124_knowledge_answer_review_ttl
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "125_knowledge_persistence_gate"
down_revision: str | Sequence[str] | None = "124_knowledge_answer_review_ttl"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_claims") as batch:
        batch.add_column(sa.Column("identity_key", sa.String(length=64), nullable=True))
    op.execute("UPDATE knowledge_claims SET identity_key = id WHERE identity_key IS NULL")
    with op.batch_alter_table("knowledge_claims") as batch:
        batch.alter_column("identity_key", existing_type=sa.String(length=64), nullable=False)
        batch.create_index("ix_knowledge_claims_identity_key", ["identity_key"])
        batch.create_unique_constraint(
            "uq_knowledge_claims_scope_identity",
            ["scope_key", "identity_key"],
        )

    with op.batch_alter_table("knowledge_relationships") as batch:
        batch.add_column(
            sa.Column("temporal_key", sa.String(length=64), nullable=False, server_default="")
        )
        batch.drop_constraint("uq_knowledge_relationships_scope_edge", type_="unique")
        batch.create_unique_constraint(
            "uq_knowledge_relationships_scope_edge",
            [
                "scope_key",
                "relation",
                "from_kind",
                "from_id",
                "to_kind",
                "to_id",
                "temporal_key",
            ],
        )

    op.create_table(
        "knowledge_observations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_key", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("observation_class", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("document_version_id", sa.String(length=64), nullable=False),
        sa.Column("question_key", sa.String(length=64), nullable=False),
        sa.Column("statement_normalized", sa.Text(), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["canonical_documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_key",
            "observation_class",
            "kind",
            "document_version_id",
            "question_key",
            "statement_normalized",
            name="uq_knowledge_observations_identity",
        ),
    )
    op.create_index(
        "ix_knowledge_observations_document_version",
        "knowledge_observations",
        ["document_version_id"],
    )
    op.create_index(
        "ix_knowledge_observations_class",
        "knowledge_observations",
        ["observation_class"],
    )
    op.create_index("ix_knowledge_observations_scope_key", "knowledge_observations", ["scope_key"])
    op.create_index(
        "ix_knowledge_observations_customer_id",
        "knowledge_observations",
        ["customer_id"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_observations")
    with op.batch_alter_table("knowledge_relationships") as batch:
        batch.drop_constraint("uq_knowledge_relationships_scope_edge", type_="unique")
        batch.create_unique_constraint(
            "uq_knowledge_relationships_scope_edge",
            ["scope_key", "relation", "from_kind", "from_id", "to_kind", "to_id"],
        )
        batch.drop_column("temporal_key")
    with op.batch_alter_table("knowledge_claims") as batch:
        batch.drop_constraint("uq_knowledge_claims_scope_identity", type_="unique")
        batch.drop_index("ix_knowledge_claims_identity_key")
        batch.drop_column("identity_key")

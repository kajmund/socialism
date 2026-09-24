"""Knowledge claims grounded in TextUnits.

Revision ID: 116_knowledge_claims
Revises: 115_canonical_text_units
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "116_knowledge_claims"
down_revision: str | Sequence[str] | None = "115_canonical_text_units"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_claims",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("document_version_id", sa.String(length=64), nullable=False),
        sa.Column("predicate", sa.String(length=128), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
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
    )
    op.create_index("ix_knowledge_claims_customer_id", "knowledge_claims", ["customer_id"])
    op.create_index("ix_knowledge_claims_document_id", "knowledge_claims", ["document_id"])
    op.create_index(
        "ix_knowledge_claims_document_version",
        "knowledge_claims",
        ["document_version_id"],
    )
    op.create_index(
        "ix_knowledge_claims_document_predicate",
        "knowledge_claims",
        ["document_id", "predicate"],
    )

    op.create_table(
        "knowledge_claim_text_units",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("claim_id", sa.String(length=64), nullable=False),
        sa.Column("text_unit_id", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["knowledge_claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["text_unit_id"], ["text_units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_id", "text_unit_id", name="uq_knowledge_claim_text_unit"),
    )
    op.create_index(
        "ix_knowledge_claim_text_units_claim_id",
        "knowledge_claim_text_units",
        ["claim_id"],
    )
    op.create_index(
        "ix_knowledge_claim_text_units_text_unit_id",
        "knowledge_claim_text_units",
        ["text_unit_id"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_claim_text_units")
    op.drop_table("knowledge_claims")

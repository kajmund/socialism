"""Add knowledge_documents index for the read-only knowledge layer.

Revision ID: 058_knowledge_documents
Revises: 057_panel_session_research_plan
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "058_knowledge_documents"
down_revision: Union[str, Sequence[str], None] = "057_panel_session_research_plan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=True),
        sa.Column("module", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("storage_bucket", sa.String(length=63), nullable=True),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False),
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
        sa.PrimaryKeyConstraint("document_id"),
        sa.UniqueConstraint(
            "provider",
            "external_id",
            name="uq_knowledge_documents_provider_external",
        ),
    )
    op.create_index(
        "ix_knowledge_documents_customer_id",
        "knowledge_documents",
        ["customer_id"],
    )
    op.create_index("ix_knowledge_documents_case_id", "knowledge_documents", ["case_id"])
    op.create_index("ix_knowledge_documents_module", "knowledge_documents", ["module"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_documents_module", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_case_id", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_customer_id", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")

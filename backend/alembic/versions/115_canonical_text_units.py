"""Canonical documents, versions, sections, text units, and Q&A provenance.

Revision ID: 115_canonical_text_units
Revises: 114_legal_question_validation
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "115_canonical_text_units"
down_revision: str | Sequence[str] | None = "114_legal_question_validation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canonical_documents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("source_object_id", sa.String(length=64), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("canonical_uri", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("domain", sa.String(length=64), nullable=True),
        sa.Column("jurisdiction", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_object_id"], ["stored_objects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "customer_id",
            "source_type",
            "canonical_uri",
            name="uq_canonical_documents_source_identity",
        ),
    )
    op.create_index("ix_canonical_documents_customer_id", "canonical_documents", ["customer_id"])
    op.create_index(
        "ix_canonical_documents_source_object_id",
        "canonical_documents",
        ["source_object_id"],
    )
    op.create_index("ix_canonical_documents_source_type", "canonical_documents", ["source_type"])
    op.create_index("ix_canonical_documents_domain", "canonical_documents", ["domain"])

    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["canonical_documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "content_hash",
            name="uq_document_versions_content_hash",
        ),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])
    op.create_index("ix_document_versions_content_hash", "document_versions", ["content_hash"])
    op.create_index(
        "ix_document_versions_superseded_at",
        "document_versions",
        ["superseded_at"],
    )
    op.create_index(
        "uq_document_versions_current",
        "document_versions",
        ["document_id"],
        unique=True,
        sqlite_where=sa.text("superseded_at IS NULL"),
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    op.create_table(
        "document_sections",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("document_version_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("parent_section_id", sa.String(length=64), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["canonical_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_section_id"], ["document_sections.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_sections_document_version_id",
        "document_sections",
        ["document_version_id"],
    )
    op.create_index("ix_document_sections_document_id", "document_sections", ["document_id"])
    op.create_index(
        "ix_document_sections_parent_section_id",
        "document_sections",
        ["parent_section_id"],
    )
    op.create_index(
        "ix_document_sections_document_ordinal",
        "document_sections",
        ["document_id", "ordinal"],
    )
    op.create_index(
        "ix_document_sections_version_ordinal",
        "document_sections",
        ["document_version_id", "ordinal"],
    )

    op.create_table(
        "text_units",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("document_version_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("section_id", sa.String(length=64), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("locator", sa.String(length=128), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("embedding_id", sa.String(length=64), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["canonical_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["document_sections.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_text_units_document_version_id", "text_units", ["document_version_id"])
    op.create_index("ix_text_units_document_id", "text_units", ["document_id"])
    op.create_index("ix_text_units_section_id", "text_units", ["section_id"])
    op.create_index("ix_text_units_document_ordinal", "text_units", ["document_id", "ordinal"])
    op.create_index(
        "ix_text_units_version_ordinal",
        "text_units",
        ["document_version_id", "ordinal"],
    )
    op.create_index("ix_text_units_content_hash", "text_units", ["content_hash"])

    op.create_table(
        "document_knowledge_item_text_units",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("text_unit_id", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_id"], ["document_knowledge_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["text_unit_id"], ["text_units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "item_id",
            "text_unit_id",
            name="uq_document_knowledge_item_text_unit",
        ),
    )
    op.create_index(
        "ix_document_knowledge_item_text_units_item_id",
        "document_knowledge_item_text_units",
        ["item_id"],
    )
    op.create_index(
        "ix_document_knowledge_item_text_units_text_unit_id",
        "document_knowledge_item_text_units",
        ["text_unit_id"],
    )


def downgrade() -> None:
    op.drop_table("document_knowledge_item_text_units")
    op.drop_table("text_units")
    op.drop_table("document_sections")
    op.drop_table("document_versions")
    op.drop_table("canonical_documents")

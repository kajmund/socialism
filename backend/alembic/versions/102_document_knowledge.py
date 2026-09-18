"""Add mutable document knowledge with source anchors and revisions.

Revision ID: 102_document_knowledge
Revises: 101_expert_knowledge_receipts
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "102_document_knowledge"
down_revision: str | Sequence[str] | None = "101_expert_knowledge_receipts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("stored_objects") as batch_op:
        batch_op.add_column(sa.Column("knowledge_status", sa.String(length=24), nullable=True))
        batch_op.add_column(sa.Column("knowledge_error", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("knowledge_job_id", sa.String(length=64), nullable=True))
        batch_op.create_foreign_key(
            "fk_stored_objects_knowledge_job_id_jobs",
            "jobs",
            ["knowledge_job_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_stored_objects_knowledge_status", ["knowledge_status"])
        batch_op.create_index("ix_stored_objects_knowledge_job_id", ["knowledge_job_id"])

    with op.batch_alter_table("knowledge_documents") as batch_op:
        batch_op.add_column(sa.Column("source_object_id", sa.String(length=64), nullable=True))
        batch_op.create_foreign_key(
            "fk_knowledge_documents_source_object_id_stored_objects",
            "stored_objects",
            ["source_object_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index(
            "ix_knowledge_documents_source_object_id",
            ["source_object_id"],
        )

    op.create_table(
        "document_knowledge_items",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source_object_id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("retrieval_queries", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=64), nullable=True),
        sa.Column("updated_by_user_id", sa.String(length=64), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["source_object_id"], ["stored_objects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["user_accounts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["user_accounts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_knowledge_items_source_object_id",
        "document_knowledge_items",
        ["source_object_id"],
    )
    op.create_index(
        "ix_document_knowledge_items_customer_id",
        "document_knowledge_items",
        ["customer_id"],
    )
    op.create_index(
        "ix_document_knowledge_items_kind",
        "document_knowledge_items",
        ["kind"],
    )
    op.create_index(
        "ix_document_knowledge_items_status",
        "document_knowledge_items",
        ["status"],
    )
    op.create_index(
        "ix_document_knowledge_items_created_by_user_id",
        "document_knowledge_items",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_document_knowledge_items_document_status",
        "document_knowledge_items",
        ["source_object_id", "status"],
    )

    op.create_table(
        "document_knowledge_anchors",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("anchor_type", sa.String(length=16), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("locator", sa.String(length=128), nullable=True),
        sa.Column("exact_text", sa.Text(), nullable=True),
        sa.Column("prefix_text", sa.Text(), nullable=True),
        sa.Column("suffix_text", sa.Text(), nullable=True),
        sa.Column("rects", sa.JSON(), nullable=False),
        sa.Column("asset_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["document_knowledge_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "item_id",
            "ordinal",
            name="uq_document_knowledge_anchor_ordinal",
        ),
    )
    op.create_index(
        "ix_document_knowledge_anchors_item_id",
        "document_knowledge_anchors",
        ["item_id"],
    )

    op.create_table(
        "document_knowledge_revisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("changed_by_user_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["document_knowledge_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_user_id"], ["user_accounts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "item_id",
            "revision",
            name="uq_document_knowledge_revision",
        ),
    )
    op.create_index(
        "ix_document_knowledge_revisions_item_id",
        "document_knowledge_revisions",
        ["item_id"],
    )
    op.create_index(
        "ix_document_knowledge_revisions_changed_by_user_id",
        "document_knowledge_revisions",
        ["changed_by_user_id"],
    )


def downgrade() -> None:
    op.drop_table("document_knowledge_revisions")
    op.drop_table("document_knowledge_anchors")
    op.drop_table("document_knowledge_items")

    with op.batch_alter_table("knowledge_documents") as batch_op:
        batch_op.drop_index("ix_knowledge_documents_source_object_id")
        batch_op.drop_constraint(
            "fk_knowledge_documents_source_object_id_stored_objects",
            type_="foreignkey",
        )
        batch_op.drop_column("source_object_id")

    with op.batch_alter_table("stored_objects") as batch_op:
        batch_op.drop_index("ix_stored_objects_knowledge_job_id")
        batch_op.drop_index("ix_stored_objects_knowledge_status")
        batch_op.drop_constraint("fk_stored_objects_knowledge_job_id_jobs", type_="foreignkey")
        batch_op.drop_column("knowledge_job_id")
        batch_op.drop_column("knowledge_error")
        batch_op.drop_column("knowledge_status")

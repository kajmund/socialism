"""Durable batch ingest with per-file upload and OverGraph progress."""

import sqlalchemy as sa
from alembic import op

revision = "176_document_ingest_batches"
down_revision = "175_passage_mark_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_ingest_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("kunder.id", ondelete="RESTRICT"), nullable=False),
        sa.Column(
            "voice_workspace_id",
            sa.String(36),
            sa.ForeignKey("voice_workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            sa.String(64),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="processing"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_document_ingest_batches_workspace",
        "document_ingest_batches",
        ["voice_workspace_id", "created_at"],
    )
    op.create_table(
        "document_ingest_batch_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(36),
            sa.ForeignKey("document_ingest_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_key", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("upload_progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ingest_progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stage", sa.String(32), nullable=False, server_default="waiting"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("searchable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "stored_object_id",
            sa.String(64),
            sa.ForeignKey("stored_objects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("document_id", sa.String(64), nullable=True),
        sa.Column("document_version_id", sa.String(64), nullable=True),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("graph_work_id", sa.String(64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_document_ingest_batch_items_batch", "document_ingest_batch_items", ["batch_id"])
    op.create_index("ix_document_ingest_batch_items_job", "document_ingest_batch_items", ["job_id"])
    op.create_index("ix_document_ingest_batch_items_work", "document_ingest_batch_items", ["graph_work_id"])


def downgrade() -> None:
    op.drop_index("ix_document_ingest_batch_items_work", table_name="document_ingest_batch_items")
    op.drop_index("ix_document_ingest_batch_items_job", table_name="document_ingest_batch_items")
    op.drop_index("ix_document_ingest_batch_items_batch", table_name="document_ingest_batch_items")
    op.drop_table("document_ingest_batch_items")
    op.drop_index("ix_document_ingest_batches_workspace", table_name="document_ingest_batches")
    op.drop_table("document_ingest_batches")

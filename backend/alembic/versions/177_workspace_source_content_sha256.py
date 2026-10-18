"""Remember file bytes so the same workspace upload can be skipped."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "177_workspace_source_content_sha256"
down_revision: str | Sequence[str] | None = "176_document_ingest_batches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("stored_objects") as batch_op:
        batch_op.add_column(sa.Column("content_sha256", sa.String(64), nullable=True))
        batch_op.create_index("ix_stored_objects_content_sha256", ["content_sha256"])
    with op.batch_alter_table("document_ingest_batch_items") as batch_op:
        batch_op.add_column(sa.Column("content_sha256", sa.String(64), nullable=True))
        batch_op.create_index("ix_document_ingest_batch_items_content_sha256", ["content_sha256"])


def downgrade() -> None:
    with op.batch_alter_table("document_ingest_batch_items") as batch_op:
        batch_op.drop_index("ix_document_ingest_batch_items_content_sha256")
        batch_op.drop_column("content_sha256")
    with op.batch_alter_table("stored_objects") as batch_op:
        batch_op.drop_index("ix_stored_objects_content_sha256")
        batch_op.drop_column("content_sha256")

"""widen research progress idempotency keys

Revision ID: 126_progress_idempotency_key
Revises: 125_question_tree_timestamps
Create Date: 2026-09-26

Parent Attempts mirror child events as ``child:{attempt_id}:{key}``.
Question-tree keys include the node id, event type, and answer id, so the
mirrored value no longer fits in varchar(128). The answer insert was in the
same transaction and rolled back, leaving the node in ``synthesizing``.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "126_progress_idempotency_key"
down_revision: str | Sequence[str] | None = "125_question_tree_timestamps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("research_progress_events") as batch:
        batch.alter_column(
            "idempotency_key",
            existing_type=sa.String(length=128),
            type_=sa.String(length=256),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("research_progress_events") as batch:
        batch.alter_column(
            "idempotency_key",
            existing_type=sa.String(length=256),
            type_=sa.String(length=128),
            existing_nullable=False,
        )

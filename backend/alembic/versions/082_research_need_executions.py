"""Per-need research execution state and evidence-id uniqueness.

Revision ID: 082_research_need_executions
Revises: 081_persona_message_image_sha256
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "082_research_need_executions"
down_revision: Union[str, Sequence[str], None] = "081_persona_message_image_sha256"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_need_executions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("research_need_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["execution_attempts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attempt_id",
            "research_need_id",
            name="uq_research_need_executions_attempt_need",
        ),
    )
    op.create_index(
        "ix_research_need_executions_attempt_id",
        "research_need_executions",
        ["attempt_id"],
    )
    with op.batch_alter_table("evidence_set_items") as batch:
        batch.create_unique_constraint(
            "uq_evidence_set_items_set_original_evidence_id",
            ["evidence_set_id", "original_evidence_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("evidence_set_items") as batch:
        batch.drop_constraint(
            "uq_evidence_set_items_set_original_evidence_id", type_="unique"
        )
    op.drop_index(
        "ix_research_need_executions_attempt_id",
        table_name="research_need_executions",
    )
    op.drop_table("research_need_executions")

"""persist decomposition exhaustion and best-effort retrieval

Revision ID: 133_decomposition_exhaustion
Revises: 132_jev_evaluation_artifacts
Create Date: 2026-09-27

Semantic exhaustion keeps the original researchability decision and records
that retrieval ran anyway. A later wave can see that this evaluation already
tried, instead of decomposing the same node again.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "133_decomposition_exhaustion"
down_revision: str | Sequence[str] | None = "132_jev_evaluation_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("research_question_nodes") as batch:
        batch.add_column(
            sa.Column(
                "decomposition_result",
                sa.String(32),
                nullable=False,
                server_default="",
            )
        )
        batch.add_column(
            sa.Column(
                "execution_override",
                sa.String(32),
                nullable=False,
                server_default="",
            )
        )
        batch.add_column(
            sa.Column(
                "execution_override_reason",
                sa.String(64),
                nullable=False,
                server_default="",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("research_question_nodes") as batch:
        batch.drop_column("execution_override_reason")
        batch.drop_column("execution_override")
        batch.drop_column("decomposition_result")

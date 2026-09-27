"""separate researchability from decomposability

Revision ID: 130_question_structure
Revises: 129_decomposition_semantic_progress
Create Date: 2026-09-27

A question can be sent to retrieval and still contain knowledge dimensions
worth representing separately. Those are stored as two decisions.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "130_question_structure"
down_revision: str | Sequence[str] | None = "129_decomposition_semantic_progress"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("research_question_nodes") as batch:
        batch.add_column(
            sa.Column(
                "researchability",
                sa.String(32),
                nullable=False,
                server_default="pending",
            )
        )
        batch.add_column(
            sa.Column(
                "researchability_noul",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            )
        )
        batch.add_column(
            sa.Column(
                "decomposability",
                sa.String(32),
                nullable=False,
                server_default="pending",
            )
        )
        batch.add_column(
            sa.Column(
                "decomposability_noul",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("research_question_nodes") as batch:
        batch.drop_column("decomposability_noul")
        batch.drop_column("decomposability")
        batch.drop_column("researchability_noul")
        batch.drop_column("researchability")

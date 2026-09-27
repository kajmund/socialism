"""content-addressed JEV evaluation artifacts

Revision ID: 132_jev_evaluation_artifacts
Revises: 131_evidence_locator_text
Create Date: 2026-09-27

Successful JEV evaluations are reused by semantic input and security scope.
The unique constraint makes concurrent writers idempotent.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "132_jev_evaluation_artifacts"
down_revision: str | Sequence[str] | None = "131_evidence_locator_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jev_evaluation_artifacts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("security_scope", sa.String(length=64), nullable=False),
        sa.Column("evaluation_key", sa.String(length=64), nullable=False),
        sa.Column("evaluator_id", sa.String(length=64), nullable=False),
        sa.Column("evaluator_version", sa.String(length=32), nullable=False),
        sa.Column("model_provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("signals", sa.JSON(), nullable=False),
        sa.Column("input_provenance", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "security_scope",
            "evaluation_key",
            name="uq_jev_evaluation_scope_key",
        ),
    )
    op.create_index(
        "ix_jev_evaluation_artifacts_evaluator",
        "jev_evaluation_artifacts",
        ["evaluator_id", "evaluator_version"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_jev_evaluation_artifacts_evaluator",
        table_name="jev_evaluation_artifacts",
    )
    op.drop_table("jev_evaluation_artifacts")

"""Drop the unused evidence-set revalidation table.

Revision ID: 190_drop_evidence_set_revalidations
Revises: 189_quick_lines_never_refuse

The table belonged to the removed legacy claim/event revalidation path: no
production code reads or writes it. The migration refuses to drop a table that
still holds rows; archive them first (see docs/audits/obsolete-2026-10-18.md).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "190_drop_evidence_set_revalidations"
down_revision: str | Sequence[str] | None = "189_quick_lines_never_refuse"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    rows = op.get_bind().execute(
        sa.text("SELECT count(*) FROM evidence_set_revalidations")
    ).scalar_one()
    if rows:
        raise RuntimeError(
            "evidence_set_revalidations still contains "
            f"{rows} rows. Archive them before dropping the table, then re-run "
            "this migration. See docs/audits/obsolete-2026-10-18.md."
        )
    op.drop_table("evidence_set_revalidations")


def downgrade() -> None:
    op.create_table(
        "evidence_set_revalidations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("evidence_set_id", sa.String(length=64), nullable=False),
        sa.Column("graph_event_id", sa.String(length=64), nullable=False),
        sa.Column("question_key", sa.String(length=64), nullable=True),
        sa.Column("knowledge_question_id", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("impact_noul", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["evidence_set_id"], ["evidence_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["graph_event_id"],
            ["knowledge_graph_events.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_question_id"],
            ["knowledge_questions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evidence_set_id",
            "graph_event_id",
            name="uq_evidence_set_revalidation_event",
        ),
    )
    op.create_index(
        "ix_evidence_set_revalidations_evidence_set_id",
        "evidence_set_revalidations",
        ["evidence_set_id"],
    )
    op.create_index(
        "ix_evidence_set_revalidations_graph_event_id",
        "evidence_set_revalidations",
        ["graph_event_id"],
    )
    op.create_index(
        "ix_evidence_set_revalidations_state",
        "evidence_set_revalidations",
        ["state"],
    )

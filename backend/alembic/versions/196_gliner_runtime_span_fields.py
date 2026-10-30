"""Optional GLiNER2 span contract on runtime research needs.

Revision ID: 196_gliner_runtime_span_fields
Revises: 195_stt_correction

span_types/span_role carry the opt-in span declaration from the plan snapshot
into the persisted runtime inventory so the span proposer sees it on every
wave. Empty span_types means the tool never applies to that need.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "196_gliner_runtime_span_fields"
down_revision: str | Sequence[str] | None = "195_stt_correction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "research_runtime_needs",
        sa.Column("span_types", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "research_runtime_needs",
        sa.Column("span_role", sa.String(length=16), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("research_runtime_needs", "span_role")
    op.drop_column("research_runtime_needs", "span_types")

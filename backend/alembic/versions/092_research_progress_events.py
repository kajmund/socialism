"""Persisted research progress events for reconnect-safe live delivery.

Revision ID: 092_research_progress_events
Revises: 091_execution_research_claims
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "092_research_progress_events"
down_revision: Union[str, Sequence[str], None] = "091_execution_research_claims"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_progress_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["execution_attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attempt_id",
            "sequence",
            name="uq_research_progress_events_attempt_sequence",
        ),
        sa.UniqueConstraint(
            "attempt_id",
            "idempotency_key",
            name="uq_research_progress_events_attempt_key",
        ),
    )
    op.create_index(
        op.f("ix_research_progress_events_attempt_id"),
        "research_progress_events",
        ["attempt_id"],
        unique=False,
    )
    op.create_index(
        "ix_research_progress_events_attempt_sequence",
        "research_progress_events",
        ["attempt_id", "sequence"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_progress_events_attempt_sequence",
        table_name="research_progress_events",
    )
    op.drop_index(
        op.f("ix_research_progress_events_attempt_id"),
        table_name="research_progress_events",
    )
    op.drop_table("research_progress_events")

"""store full evidence locators

Revision ID: 131_evidence_locator_text
Revises: 130_question_structure
Create Date: 2026-09-27

A reused claim locator is the comma-joined list of supporting text-unit ids.
That list is longer than varchar(512) when a claim rests on many units.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "131_evidence_locator_text"
down_revision: str | Sequence[str] | None = "130_question_structure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "evidence_passages",
    "evidence_set_items",
    "knowledge_question_evidence_links",
)


def upgrade() -> None:
    """Upgrade schema."""
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "locator",
                existing_type=sa.String(512),
                type_=sa.Text(),
                existing_nullable=True,
            )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    for table in _TABLES:
        oversized = bind.execute(
            sa.text(f"SELECT 1 FROM {table} WHERE length(locator) > 512 LIMIT 1")
        ).first()
        if oversized:
            raise ValueError(f"Cannot downgrade {table}.locator without losing long locators")
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "locator",
                existing_type=sa.Text(),
                type_=sa.String(512),
                existing_nullable=True,
            )

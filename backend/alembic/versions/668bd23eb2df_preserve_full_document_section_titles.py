"""preserve full document section titles

Revision ID: 668bd23eb2df
Revises: 123_knowledge_tenant_scope
Create Date: 2026-09-26 06:45:41.435841

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "668bd23eb2df"
down_revision: str | Sequence[str] | None = "123_knowledge_tenant_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("document_sections") as batch:
        batch.alter_column(
            "title", existing_type=sa.String(512), type_=sa.Text(), existing_nullable=True
        )


def downgrade() -> None:
    """Downgrade schema."""
    oversized = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM document_sections WHERE length(title) > 512 LIMIT 1"))
        .first()
    )
    if oversized:
        raise ValueError("Cannot downgrade document_sections.title without losing long titles")
    with op.batch_alter_table("document_sections") as batch:
        batch.alter_column(
            "title", existing_type=sa.Text(), type_=sa.String(512), existing_nullable=True
        )

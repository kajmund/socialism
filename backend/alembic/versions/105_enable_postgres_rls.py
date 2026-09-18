"""Enable RLS for application-owned PostgreSQL tables.

Revision ID: 105_enable_postgres_rls
Revises: 104_document_knowledge_focus
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "105_enable_postgres_rls"
down_revision: str | Sequence[str] | None = "104_document_knowledge_focus"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _owned_public_tables() -> list[str]:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return []
    return list(
        connection.execute(
            sa.text(
                """
                SELECT tablename
                FROM pg_catalog.pg_tables
                WHERE schemaname = 'public'
                  AND tableowner = current_user
                ORDER BY tablename
                """
            )
        ).scalars()
    )


def _set_rls(*, enabled: bool) -> None:
    connection = op.get_bind()
    quote = connection.dialect.identifier_preparer.quote
    action = "ENABLE" if enabled else "DISABLE"
    for table_name in _owned_public_tables():
        connection.execute(
            sa.text(f"ALTER TABLE public.{quote(table_name)} {action} ROW LEVEL SECURITY")
        )


def upgrade() -> None:
    _set_rls(enabled=True)


def downgrade() -> None:
    _set_rls(enabled=False)

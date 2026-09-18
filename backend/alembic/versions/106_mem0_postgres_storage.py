"""Store Mem0 vectors and history in PostgreSQL.

Revision ID: 106_mem0_postgres_storage
Revises: 105_enable_postgres_rls
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "106_mem0_postgres_storage"
down_revision: str | Sequence[str] | None = "105_enable_postgres_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE mem0_history (
            id text PRIMARY KEY,
            memory_id text NOT NULL,
            old_memory text,
            new_memory text,
            event text NOT NULL,
            created_at text,
            updated_at text,
            is_deleted boolean NOT NULL DEFAULT false,
            actor_id text,
            role text
        )
        """
    )
    op.create_index("ix_mem0_history_memory_id", "mem0_history", ["memory_id"])
    op.execute(
        """
        CREATE TABLE mem0_messages (
            id text PRIMARY KEY,
            session_scope text NOT NULL,
            role text,
            content jsonb,
            name text,
            created_at text NOT NULL
        )
        """
    )
    op.create_index(
        "ix_mem0_messages_scope_created",
        "mem0_messages",
        ["session_scope", "created_at"],
    )

    for table_name in ("expert_memories", "expert_memories_entities"):
        op.execute(
            sa.text(
                f"""
                CREATE TABLE {table_name} (
                    id uuid PRIMARY KEY,
                    vector vector(1536),
                    payload jsonb
                )
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE INDEX {table_name}_hnsw_idx ON {table_name}
                USING hnsw (vector vector_cosine_ops)
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE INDEX {table_name}_text_lemmatized_idx ON {table_name}
                USING gin(to_tsvector('simple', payload->>'text_lemmatized'))
                """
            )
        )

    for table_name in (
        "mem0_history",
        "mem0_messages",
        "expert_memories",
        "expert_memories_entities",
    ):
        op.execute(sa.text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return
    op.drop_table("expert_memories_entities")
    op.drop_table("expert_memories")
    op.drop_index("ix_mem0_messages_scope_created", table_name="mem0_messages")
    op.drop_table("mem0_messages")
    op.drop_index("ix_mem0_history_memory_id", table_name="mem0_history")
    op.drop_table("mem0_history")

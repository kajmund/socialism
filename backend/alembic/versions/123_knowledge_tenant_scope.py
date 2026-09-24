"""Explicit shared|customer scope on the knowledge pipeline.

Revision ID: 123_knowledge_tenant_scope
Revises: 122_knowledge_question_iteration
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "123_knowledge_tenant_scope"
down_revision: str | Sequence[str] | None = "122_knowledge_question_iteration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE_CHECK = (
    "(scope_type = 'shared' AND customer_id IS NULL AND scope_key = 'shared') OR "
    "(scope_type = 'customer' AND customer_id IS NOT NULL AND "
    "scope_key = 'customer:' || customer_id)"
)

_PARENT_SCOPED = (
    "canonical_documents",
    "knowledge_claims",
    "knowledge_entities",
    "knowledge_relationships",
    "knowledge_graph_events",
    "knowledge_questions",
)

_CHILD_FROM_DOCUMENT = (
    "document_versions",
    "document_sections",
    "text_units",
)


def upgrade() -> None:
    for table in _PARENT_SCOPED:
        _add_scope_columns(table, include_customer_id=False)
        if table == "knowledge_questions":
            op.execute(
                sa.text(
                    "UPDATE knowledge_questions SET "
                    "scope_type = CASE WHEN visibility = 'public' THEN 'shared' "
                    "ELSE 'customer' END, "
                    "scope_key = CASE WHEN visibility = 'public' THEN 'shared' "
                    "ELSE 'customer:' || customer_id END"
                )
            )
        else:
            op.execute(
                sa.text(
                    f"UPDATE {table} SET "
                    "scope_type = 'customer', "
                    "scope_key = 'customer:' || customer_id "
                    "WHERE customer_id IS NOT NULL"
                )
            )
        _finalize_scope_columns(table, make_customer_nullable=True)

    for table in _CHILD_FROM_DOCUMENT:
        _add_scope_columns(table, include_customer_id=True)
        op.execute(
            sa.text(
                f"UPDATE {table} SET "
                "scope_type = (SELECT scope_type FROM canonical_documents "
                f"WHERE canonical_documents.id = {table}.document_id), "
                "scope_key = (SELECT scope_key FROM canonical_documents "
                f"WHERE canonical_documents.id = {table}.document_id), "
                "customer_id = (SELECT customer_id FROM canonical_documents "
                f"WHERE canonical_documents.id = {table}.document_id)"
            )
        )
        _finalize_scope_columns(table, make_customer_nullable=False)

    _add_scope_columns("knowledge_claim_answers", include_customer_id=True)
    op.execute(
        sa.text(
            "UPDATE knowledge_claim_answers SET "
            "scope_type = (SELECT scope_type FROM knowledge_claims "
            "WHERE knowledge_claims.id = knowledge_claim_answers.claim_id), "
            "scope_key = (SELECT scope_key FROM knowledge_claims "
            "WHERE knowledge_claims.id = knowledge_claim_answers.claim_id), "
            "customer_id = (SELECT customer_id FROM knowledge_claims "
            "WHERE knowledge_claims.id = knowledge_claim_answers.claim_id)"
        )
    )
    _finalize_scope_columns("knowledge_claim_answers", make_customer_nullable=False)

    with op.batch_alter_table("canonical_documents") as batch:
        batch.drop_constraint("uq_canonical_documents_source_identity", type_="unique")
        batch.create_unique_constraint(
            "uq_canonical_documents_scope_identity",
            ["scope_key", "source_type", "canonical_uri"],
        )
    with op.batch_alter_table("knowledge_entities") as batch:
        batch.drop_constraint("uq_knowledge_entities_identity", type_="unique")
        batch.create_unique_constraint(
            "uq_knowledge_entities_scope_identity",
            ["scope_key", "entity_type", "entity_key"],
        )
    with op.batch_alter_table("knowledge_relationships") as batch:
        batch.drop_constraint("uq_knowledge_relationships_edge", type_="unique")
        batch.create_unique_constraint(
            "uq_knowledge_relationships_scope_edge",
            ["scope_key", "relation", "from_kind", "from_id", "to_kind", "to_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_relationships") as batch:
        batch.drop_constraint("uq_knowledge_relationships_scope_edge", type_="unique")
        batch.create_unique_constraint(
            "uq_knowledge_relationships_edge",
            ["customer_id", "relation", "from_kind", "from_id", "to_kind", "to_id"],
        )
    with op.batch_alter_table("knowledge_entities") as batch:
        batch.drop_constraint("uq_knowledge_entities_scope_identity", type_="unique")
        batch.create_unique_constraint(
            "uq_knowledge_entities_identity",
            ["customer_id", "entity_type", "entity_key"],
        )
    with op.batch_alter_table("canonical_documents") as batch:
        batch.drop_constraint("uq_canonical_documents_scope_identity", type_="unique")
        batch.create_unique_constraint(
            "uq_canonical_documents_source_identity",
            ["customer_id", "source_type", "canonical_uri"],
        )
    for table in (
        "knowledge_claim_answers",
        *_CHILD_FROM_DOCUMENT,
        *_PARENT_SCOPED,
    ):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"ck_{table}_knowledge_scope", type_="check")
            if table in _CHILD_FROM_DOCUMENT or table == "knowledge_claim_answers":
                batch.drop_constraint(f"fk_{table}_knowledge_scope_customer", type_="foreignkey")
                batch.drop_index(f"ix_{table}_customer_id")
                batch.drop_column("customer_id")
            batch.drop_index(f"ix_{table}_scope_key")
            batch.drop_index(f"ix_{table}_scope_type")
            batch.drop_column("scope_key")
            batch.drop_column("scope_type")


def _add_scope_columns(table: str, *, include_customer_id: bool) -> None:
    with op.batch_alter_table(table) as batch:
        batch.add_column(sa.Column("scope_type", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("scope_key", sa.String(length=64), nullable=True))
        if include_customer_id:
            batch.add_column(sa.Column("customer_id", sa.Integer(), nullable=True))


def _finalize_scope_columns(table: str, *, make_customer_nullable: bool) -> None:
    with op.batch_alter_table(table) as batch:
        batch.alter_column("scope_type", existing_type=sa.String(length=16), nullable=False)
        batch.alter_column("scope_key", existing_type=sa.String(length=64), nullable=False)
        if make_customer_nullable:
            batch.alter_column("customer_id", existing_type=sa.Integer(), nullable=True)
        batch.create_index(f"ix_{table}_scope_type", ["scope_type"])
        batch.create_index(f"ix_{table}_scope_key", ["scope_key"])
        if table in _CHILD_FROM_DOCUMENT or table == "knowledge_claim_answers":
            batch.create_index(f"ix_{table}_customer_id", ["customer_id"])
            batch.create_foreign_key(
                f"fk_{table}_knowledge_scope_customer",
                "kunder",
                ["customer_id"],
                ["id"],
                ondelete="RESTRICT",
            )
        batch.create_check_constraint(f"ck_{table}_knowledge_scope", _SCOPE_CHECK)

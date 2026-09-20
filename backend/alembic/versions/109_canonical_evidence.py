"""Canonical evidence sources, passages, and runtime need links.

Revision ID: 109_canonical_evidence
Revises: 108_research_evaluation_prompt_defaults
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from urllib.parse import urlsplit, urlunsplit

import sqlalchemy as sa

from alembic import op

revision: str = "109_canonical_evidence"
down_revision: str | Sequence[str] | None = "108_research_evaluation_prompt_defaults"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _canonical(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if "://" not in value:
        return value.split("#", 1)[0]
    parts = urlsplit(value)
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path.rstrip("/"),
            parts.query,
            "",
        )
    )


def _ids(row: sa.RowMapping) -> tuple[str, str, str]:
    content_hash = str(row.get("content_hash") or hashlib.sha256(
        str(row.get("excerpt") or "").encode()
    ).hexdigest())
    identity = _canonical(row.get("source_id") or row.get("source_url"))
    if not identity:
        identity = f"content:{content_hash}"
    source_key = hashlib.sha256(
        f"{row.get('provider') or ''}\x1f{identity}".encode()
    ).hexdigest()
    passage_key = hashlib.sha256(
        "\x1f".join(
            (
                source_key,
                str(row.get("source_id") or ""),
                str(row.get("locator") or ""),
                content_hash,
            )
        ).encode()
    ).hexdigest()
    return source_key, passage_key, content_hash


def _upsert_canonical(conn, row: sa.RowMapping) -> tuple[str, str]:
    source_key, passage_key, content_hash = _ids(row)
    conn.execute(
        sa.text(
            "INSERT INTO evidence_sources "
            "(id, provider, canonical_identity, source_type, source_id, source_url, title) "
            "VALUES (:id, :provider, :identity, :source_type, :source_id, :source_url, :title) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": source_key,
            "provider": row.get("provider"),
            "identity": _canonical(row.get("source_id") or row.get("source_url"))
            or f"content:{content_hash}",
            "source_type": row.get("source_type") or "unknown",
            "source_id": row.get("source_id"),
            "source_url": row.get("source_url"),
            "title": row.get("title"),
        },
    )
    conn.execute(
        sa.text(
            "INSERT INTO evidence_passages "
            "(id, source_id, source_ref, locator, excerpt, content_hash, provenance, retrieved_at) "
            "VALUES (:id, :source_id, :source_ref, :locator, :excerpt, :content_hash, "
            ":provenance, :retrieved_at) ON CONFLICT (id) DO NOTHING"
        ).bindparams(sa.bindparam("provenance", type_=sa.JSON())),
        {
            "id": passage_key,
            "source_id": source_key,
            "source_ref": row.get("source_id"),
            "locator": row.get("locator"),
            "excerpt": row.get("excerpt"),
            "content_hash": content_hash,
            "provenance": row.get("provenance") or {},
            "retrieved_at": row.get("retrieved_at") or row.get("observed_at"),
        },
    )
    return source_key, passage_key


def upgrade() -> None:
    op.create_table(
        "evidence_sources",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("canonical_identity", sa.String(1024), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(512), nullable=True),
        sa.Column("source_url", sa.String(1024), nullable=True),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "evidence_passages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("evidence_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_ref", sa.String(512), nullable=True),
        sa.Column("locator", sa.String(512), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_evidence_passages_source_id", "evidence_passages", ["source_id"])
    with op.batch_alter_table("evidence_set_items") as batch:
        batch.add_column(sa.Column("passage_id", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_evidence_set_items_passage",
            "evidence_passages",
            ["passage_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index("ix_evidence_set_items_passage_id", "evidence_set_items", ["passage_id"])
    op.create_table(
        "evidence_set_item_needs",
        sa.Column(
            "evidence_set_item_id",
            sa.String(64),
            sa.ForeignKey("evidence_set_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("research_need_id", sa.String(64), primary_key=True),
    )
    with op.batch_alter_table("knowledge_question_evidence_links") as batch:
        batch.add_column(sa.Column("passage_id", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_knowledge_question_evidence_links_passage",
            "evidence_passages",
            ["passage_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_knowledge_question_evidence_links_passage_id",
        "knowledge_question_evidence_links",
        ["passage_id"],
    )

    conn = op.get_bind()
    item_rows = conn.execute(sa.text("SELECT * FROM evidence_set_items ORDER BY ordinal, id")).mappings().all()
    keeper_by_set_passage: dict[tuple[str, str], str] = {}
    for row in item_rows:
        _source_key, passage_key = _upsert_canonical(conn, row)
        key = (str(row["evidence_set_id"]), passage_key)
        keeper = keeper_by_set_passage.get(key)
        if keeper is None:
            keeper = str(row["id"])
            keeper_by_set_passage[key] = keeper
            conn.execute(
                sa.text("UPDATE evidence_set_items SET passage_id=:passage WHERE id=:id"),
                {"passage": passage_key, "id": keeper},
            )
        if row.get("research_need_id"):
            conn.execute(
                sa.text(
                    "INSERT INTO evidence_set_item_needs "
                    "(evidence_set_item_id, research_need_id) VALUES (:item, :need) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"item": keeper, "need": row["research_need_id"]},
            )
        if keeper != row["id"]:
            qualities = conn.execute(
                sa.text(
                    "SELECT id, scoring_policy_version, model_identity_key "
                    "FROM research_evidence_quality WHERE evidence_set_item_id=:id"
                ),
                {"id": row["id"]},
            ).mappings().all()
            for quality in qualities:
                exists = conn.execute(
                    sa.text(
                        "SELECT id FROM research_evidence_quality "
                        "WHERE evidence_set_item_id=:keeper "
                        "AND scoring_policy_version=:policy AND model_identity_key=:model"
                    ),
                    {
                        "keeper": keeper,
                        "policy": quality["scoring_policy_version"],
                        "model": quality["model_identity_key"],
                    },
                ).first()
                if exists:
                    conn.execute(sa.text("DELETE FROM research_evidence_quality WHERE id=:id"), {"id": quality["id"]})
                else:
                    conn.execute(
                        sa.text("UPDATE research_evidence_quality SET evidence_set_item_id=:keeper WHERE id=:id"),
                        {"keeper": keeper, "id": quality["id"]},
                    )
            conn.execute(sa.text("DELETE FROM evidence_set_items WHERE id=:id"), {"id": row["id"]})

    link_rows = conn.execute(sa.text("SELECT * FROM knowledge_question_evidence_links ORDER BY created_at, id")).mappings().all()
    keeper_by_question_passage: dict[tuple[str, str], str] = {}
    for row in link_rows:
        _source_key, passage_key = _upsert_canonical(conn, row)
        key = (str(row["question_id"]), passage_key)
        if key in keeper_by_question_passage:
            conn.execute(sa.text("DELETE FROM knowledge_question_evidence_links WHERE id=:id"), {"id": row["id"]})
            continue
        keeper_by_question_passage[key] = str(row["id"])
        conn.execute(
            sa.text(
                "UPDATE knowledge_question_evidence_links SET passage_id=:passage WHERE id=:id"
            ),
            {"passage": passage_key, "id": row["id"]},
        )

    conn.execute(
        sa.text(
            "UPDATE knowledge_question_evidence_links SET "
            "title=NULL, excerpt=NULL, locator=NULL, source_id=NULL, source_url=NULL, "
            "source_type=NULL, provider=NULL WHERE passage_id IS NOT NULL"
        )
    )

    with op.batch_alter_table("evidence_set_items") as batch:
        batch.create_unique_constraint(
            "uq_evidence_set_items_set_passage",
            ["evidence_set_id", "passage_id"],
        )
    with op.batch_alter_table("knowledge_question_evidence_links") as batch:
        batch.create_unique_constraint(
            "uq_knowledge_question_passage",
            ["question_id", "passage_id"],
        )


def downgrade() -> None:
    op.drop_index("ix_knowledge_question_evidence_links_passage_id", table_name="knowledge_question_evidence_links")
    with op.batch_alter_table("knowledge_question_evidence_links") as batch:
        batch.drop_constraint("uq_knowledge_question_passage", type_="unique")
        batch.drop_constraint(
            "fk_knowledge_question_evidence_links_passage", type_="foreignkey"
        )
        batch.drop_column("passage_id")
    op.drop_table("evidence_set_item_needs")
    op.drop_index("ix_evidence_set_items_passage_id", table_name="evidence_set_items")
    with op.batch_alter_table("evidence_set_items") as batch:
        batch.drop_constraint("uq_evidence_set_items_set_passage", type_="unique")
        batch.drop_constraint("fk_evidence_set_items_passage", type_="foreignkey")
        batch.drop_column("passage_id")
    op.drop_index("ix_evidence_passages_source_id", table_name="evidence_passages")
    op.drop_table("evidence_passages")
    op.drop_table("evidence_sources")

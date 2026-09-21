"""Persist raw sources, question-specific domain results and grounded claims.

Revision ID: 111_raw_domain_claims
Revises: 110_lagen_nu_selector_prompts
"""

from __future__ import annotations

import hashlib

import sqlalchemy as sa

from alembic import op
from app.services.legal_research_result import LegalResearchResult
from app.services.research_domain_results import domain_result_id, legal_claims, raw_source_id

revision = "111_raw_domain_claims"
down_revision = "110_lagen_nu_selector_prompts"
branch_labels = None
depends_on = None


def _persist_orphaned_legal(conn, *, source_key: str, need_id: str, raw: dict) -> str:
    """Move legacy graph/passage blobs even when no EvidenceSet item references them."""
    result = LegalResearchResult.model_validate(raw)
    raw_id = raw_source_id(source_key, result.raw_text)
    result_id = domain_result_id(raw_id, need_id, result)
    conn.execute(
        sa.text(
            "INSERT INTO raw_sources (id, source_id, content_hash, raw_text, truncated) "
            "VALUES (:id, :source, :hash, :text, :truncated) ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": raw_id,
            "source": source_key,
            "hash": hashlib.sha256(result.raw_text.encode("utf-8")).hexdigest(),
            "text": result.raw_text,
            "truncated": result.truncated,
        },
    )
    existing = (
        conn.execute(
            sa.text(
                "SELECT id, result FROM domain_research_results WHERE raw_source_id=:raw AND domain='legal'"
            ).columns(result=sa.JSON()),
            {"raw": raw_id},
        )
        .mappings()
        .all()
    )
    for row in existing:
        if row["result"] == result.model_dump(mode="json", exclude={"raw_text"}):
            return str(row["id"])
    conn.execute(
        sa.text(
            "INSERT INTO domain_research_results (id, raw_source_id, research_need_id, domain, schema_version, result) "
            "VALUES (:id, :raw, :need, 'legal', 2, :result) ON CONFLICT (id) DO NOTHING"
        ).bindparams(sa.bindparam("result", type_=sa.JSON())),
        {
            "id": result_id,
            "raw": raw_id,
            "need": need_id,
            "result": result.model_dump(mode="json", exclude={"raw_text"}),
        },
    )
    for claim in legal_claims(result, result_id=result_id, research_need_id=need_id):
        conn.execute(
            sa.text(
                "INSERT INTO research_claims (id, domain_result_id, research_need_id, predicate, value, relation, citations) "
                "VALUES (:id, :result, :need, :predicate, :value, :relation, :citations) ON CONFLICT (id) DO NOTHING"
            ).bindparams(
                sa.bindparam("value", type_=sa.JSON()), sa.bindparam("citations", type_=sa.JSON())
            ),
            {
                "id": claim.id,
                "result": result_id,
                "need": need_id,
                "predicate": claim.predicate,
                "value": claim.value,
                "relation": claim.relation,
                "citations": claim.citations,
            },
        )
    return result_id


def upgrade() -> None:
    op.create_table(
        "raw_sources",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(64),
            sa.ForeignKey("evidence_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_raw_sources_source_id", "raw_sources", ["source_id"])
    op.create_table(
        "domain_research_results",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "raw_source_id",
            sa.String(64),
            sa.ForeignKey("raw_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("research_need_id", sa.String(64), nullable=False),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_domain_research_results_raw_source_id", "domain_research_results", ["raw_source_id"]
    )
    op.create_index(
        "ix_domain_research_results_research_need_id",
        "domain_research_results",
        ["research_need_id"],
    )
    op.create_table(
        "research_claims",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "domain_result_id",
            sa.String(64),
            sa.ForeignKey("domain_research_results.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("research_need_id", sa.String(64), nullable=False),
        sa.Column("predicate", sa.String(128), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("relation", sa.String(32), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_research_claims_domain_result_id", "research_claims", ["domain_result_id"])
    op.create_index("ix_research_claims_research_need_id", "research_claims", ["research_need_id"])
    if op.get_bind().dialect.name == "postgresql":
        for table in ("raw_sources", "domain_research_results", "research_claims"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    with op.batch_alter_table("evidence_set_items") as batch:
        batch.add_column(sa.Column("domain_result_id", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_evidence_set_items_domain_result",
            "domain_research_results",
            ["domain_result_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_evidence_set_items_domain_result_id", "evidence_set_items", ["domain_result_id"]
    )

    conn = op.get_bind()
    rows = (
        conn.execute(
            sa.text(
                "SELECT id, passage_id, research_need_id, provenance FROM evidence_set_items WHERE passage_id IS NOT NULL"
            ).columns(provenance=sa.JSON())
        )
        .mappings()
        .all()
    )
    for row in rows:
        provenance = dict(row["provenance"] or {})
        raw = provenance.pop("legal_result", None)
        if not raw:
            continue
        result = LegalResearchResult.model_validate(raw)
        source_key = conn.execute(
            sa.text("SELECT source_id FROM evidence_passages WHERE id=:id"),
            {"id": row["passage_id"]},
        ).scalar_one()
        raw_id = raw_source_id(source_key, result.raw_text)
        need_id = str(row["research_need_id"] or "")
        result_id = domain_result_id(raw_id, need_id, result)
        conn.execute(
            sa.text(
                "INSERT INTO raw_sources (id, source_id, content_hash, raw_text, truncated) VALUES (:id, :source, :hash, :text, :truncated) ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": raw_id,
                "source": source_key,
                "hash": hashlib.sha256(result.raw_text.encode("utf-8")).hexdigest(),
                "text": result.raw_text,
                "truncated": result.truncated,
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO domain_research_results (id, raw_source_id, research_need_id, domain, schema_version, result) VALUES (:id, :raw, :need, 'legal', 2, :result) ON CONFLICT (id) DO NOTHING"
            ).bindparams(sa.bindparam("result", type_=sa.JSON())),
            {
                "id": result_id,
                "raw": raw_id,
                "need": need_id,
                "result": result.model_dump(mode="json", exclude={"raw_text"}),
            },
        )
        for claim in legal_claims(result, result_id=result_id, research_need_id=need_id):
            conn.execute(
                sa.text(
                    "INSERT INTO research_claims (id, domain_result_id, research_need_id, predicate, value, relation, citations) VALUES (:id, :result, :need, :predicate, :value, :relation, :citations) ON CONFLICT (id) DO NOTHING"
                ).bindparams(
                    sa.bindparam("value", type_=sa.JSON()),
                    sa.bindparam("citations", type_=sa.JSON()),
                ),
                {
                    "id": claim.id,
                    "result": result_id,
                    "need": need_id,
                    "predicate": claim.predicate,
                    "value": claim.value,
                    "relation": claim.relation,
                    "citations": claim.citations,
                },
            )
        conn.execute(
            sa.text(
                "UPDATE evidence_set_items SET domain_result_id=:result, provenance=:provenance WHERE id=:id"
            ).bindparams(sa.bindparam("provenance", type_=sa.JSON())),
            {
                "id": row["id"],
                "result": result_id,
                "provenance": provenance,
            },
        )
    links = (
        conn.execute(
            sa.text(
                "SELECT id, question_id, passage_id, provenance FROM knowledge_question_evidence_links WHERE passage_id IS NOT NULL"
            ).columns(provenance=sa.JSON())
        )
        .mappings()
        .all()
    )
    for link in links:
        provenance = dict(link["provenance"] or {})
        raw = provenance.pop("legal_result", None)
        if not raw:
            continue
        source_key = conn.execute(
            sa.text("SELECT source_id FROM evidence_passages WHERE id=:id"),
            {"id": link["passage_id"]},
        ).scalar_one()
        result_id = _persist_orphaned_legal(
            conn, source_key=source_key, need_id=f"question:{link['question_id']}", raw=raw
        )
        provenance["domain_result_id"] = result_id
        conn.execute(
            sa.text(
                "UPDATE knowledge_question_evidence_links SET provenance=:provenance WHERE id=:id"
            ).bindparams(sa.bindparam("provenance", type_=sa.JSON())),
            {"id": link["id"], "provenance": provenance},
        )
    passages = (
        conn.execute(
            sa.text("SELECT id, source_id, provenance FROM evidence_passages").columns(
                provenance=sa.JSON()
            )
        )
        .mappings()
        .all()
    )
    for passage in passages:
        provenance = dict(passage["provenance"] or {})
        raw = provenance.pop("legal_result", None)
        if not raw:
            continue
        linked = conn.execute(
            sa.text(
                "SELECT domain_result_id FROM evidence_set_items WHERE passage_id=:id AND domain_result_id IS NOT NULL LIMIT 1"
            ),
            {"id": passage["id"]},
        ).scalar()
        if not linked:
            _persist_orphaned_legal(
                conn, source_key=passage["source_id"], need_id=f"passage:{passage['id']}", raw=raw
            )
        conn.execute(
            sa.text("UPDATE evidence_passages SET provenance=:provenance WHERE id=:id").bindparams(
                sa.bindparam("provenance", type_=sa.JSON())
            ),
            {"id": passage["id"], "provenance": provenance},
        )


def downgrade() -> None:
    op.drop_index("ix_evidence_set_items_domain_result_id", table_name="evidence_set_items")
    with op.batch_alter_table("evidence_set_items") as batch:
        batch.drop_constraint("fk_evidence_set_items_domain_result", type_="foreignkey")
        batch.drop_column("domain_result_id")
    op.drop_index("ix_research_claims_research_need_id", table_name="research_claims")
    op.drop_index("ix_research_claims_domain_result_id", table_name="research_claims")
    op.drop_table("research_claims")
    op.drop_index(
        "ix_domain_research_results_research_need_id", table_name="domain_research_results"
    )
    op.drop_index("ix_domain_research_results_raw_source_id", table_name="domain_research_results")
    op.drop_table("domain_research_results")
    op.drop_index("ix_raw_sources_source_id", table_name="raw_sources")
    op.drop_table("raw_sources")

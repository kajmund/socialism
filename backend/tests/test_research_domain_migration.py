"""Migration preserves pre-v2 legal snapshots without retaining raw blobs in provenance."""

import json
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from app.services.legal_research_result import (
    LegalCitation,
    LegalQuestionRelation,
    LegalResearchResult,
    LegalSourceIdentity,
    StatuteAnalysis,
)


def test_legacy_legal_provenance_is_moved_to_versioned_records(tmp_path, monkeypatch):
    path = tmp_path / "research-migration.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    backend = Path(__file__).resolve().parents[1]

    def upgrade(revision: str) -> None:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", revision],
            cwd=backend,
            check=True,
            capture_output=True,
            text=True,
        )

    upgrade("110_lagen_nu_selector_prompts")
    uri = "https://lagen.nu/1981:130#P2"
    raw = "En fordran preskriberas tio år efter tillkomsten."
    result = LegalResearchResult(
        source=LegalSourceIdentity(kind="statute", title="Preskriptionslag", canonical_uri=uri),
        relation=LegalQuestionRelation(
            relation="supports", explanation="Relevant", confidence="high"
        ),
        statute=StatuteAnalysis(
            operative_rule="Preskription efter tio år",
            citations=[LegalCitation(source_uri=uri, quote="fordran preskriberas")],
        ),
        raw_text=raw,
    )
    provenance = json.dumps({"legal_result": result.model_dump(mode="json"), "retrieval": "test"})
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO evidence_sources (id, canonical_identity, source_type) VALUES ('source-1', :uri, 'swedish_law')"
            ),
            {"uri": uri},
        )
        conn.execute(
            text(
                "INSERT INTO evidence_passages (id, source_id, content_hash, provenance, retrieved_at) VALUES ('passage-1', 'source-1', 'hash', :provenance, CURRENT_TIMESTAMP)"
            ),
            {"provenance": provenance},
        )
        conn.execute(
            text(
                "INSERT INTO evidence_set_items (id, evidence_set_id, research_need_id, passage_id, ordinal, source_type, status, provenance, retrieved_at, content_hash) VALUES ('item-1', 'set-1', 'need-1', 'passage-1', 0, 'swedish_law', 'found', :provenance, CURRENT_TIMESTAMP, 'hash')"
            ),
            {"provenance": provenance},
        )
        conn.execute(
            text(
                "INSERT INTO knowledge_question_evidence_links (id, question_id, evidence_ref, relation, passage_id, provenance, freshness, visibility) VALUES ('link-1', 'question-1', 'ref-1', 'ANSWERED_BY', 'passage-1', :provenance, 'fresh', 'public')"
            ),
            {"provenance": provenance},
        )
    upgrade("head")
    with engine.connect() as conn:
        item = conn.execute(
            text("SELECT domain_result_id, provenance FROM evidence_set_items WHERE id='item-1'")
        ).one()
        assert item.domain_result_id
        assert json.loads(item.provenance) == {"retrieval": "test"}
        assert conn.execute(text("SELECT raw_text FROM raw_sources")).scalar_one() == raw
        assert (
            conn.execute(
                text("SELECT research_need_id FROM domain_research_results WHERE id=:id"),
                {"id": item.domain_result_id},
            ).scalar_one()
            == "need-1"
        )
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM research_claims WHERE domain_result_id=:id"),
                {"id": item.domain_result_id},
            ).scalar_one()
            > 0
        )
        assert "legal_result" not in json.loads(
            conn.execute(
                text("SELECT provenance FROM evidence_passages WHERE id='passage-1'")
            ).scalar_one()
        )
        link = json.loads(
            conn.execute(
                text("SELECT provenance FROM knowledge_question_evidence_links WHERE id='link-1'")
            ).scalar_one()
        )
        assert link["domain_result_id"] == item.domain_result_id
        assert "legal_result" not in link
    engine.dispose()

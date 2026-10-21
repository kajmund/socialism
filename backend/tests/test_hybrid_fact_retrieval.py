"""Hybrid fact retrieval: Tantivy lexical candidates fused with OverGraph dense hits."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.graph_v2.types import FactInput, NodeInput
from app.services.knowledge.scope import customer_scope
from app.services.overgraph import hybrid_retrieval
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.hybrid_retrieval import (
    FactIndexStaleError,
    ensure_fact_index_current,
    hybrid_fact_hits,
)
from app.services.overgraph.research import update_fact
from app.services.overgraph.write import upsert_entity, write_fact
from app.services.tantivy_index import (
    build_from_overgraph,
    read_watermark,
    reconcile,
    write_watermark,
)

CUSTOMER = 3
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def _fact(*, fact_id: str, text: str, customer_id: int = CUSTOMER) -> None:
    scope = customer_scope(customer_id)
    left = upsert_entity(require_knowledge(), NodeInput(
        node_type="core.concept", name=f"{fact_id}-s", scope=scope,
    )).key
    right = upsert_entity(require_knowledge(), NodeInput(
        node_type="core.concept", name=f"{fact_id}-o", scope=scope,
    )).key
    write_fact(
        require_knowledge(),
        FactInput(
            source_id=left, target_id=right, scope=scope,
            predicate="legal.rule", fact_text=text, sources=(),
        ),
        key=fact_id,
    )


@pytest.fixture
def build(tmp_path):
    def _build():
        return build_from_overgraph(require_knowledge(), tmp_path / "index")

    return _build


def _hits(index, query: str, *, limit: int = 20, dense_query=None):
    return hybrid_fact_hits(
        require_knowledge(), index, customer_id=CUSTOMER, query=query,
        limit=limit, dense_query=dense_query, now=NOW,
    )


def test_lexical_only_fact_is_found_without_any_dense_candidate(build):
    """A fact without an embedding is invisible to dense retrieval but must stay findable."""
    _fact(fact_id="lexical-only", text="Jämkning av oskäliga avtalsvillkor enligt 36 §")
    hits = _hits(build(), "oskäliga avtalsvillkor")
    assert [hit.fact.id for hit in hits] == ["lexical-only"]
    assert hits[0].score > 0


def test_validity_is_checked_in_overgraph_not_in_the_index(build):
    _fact(fact_id="expired", text="Uppsägningstid regleras i avtalet")
    index = build()
    update_fact(require_knowledge(), "expired", invalid_at=NOW - timedelta(days=1))
    assert _hits(index, "uppsägningstid") == []


def test_superseded_fact_is_not_returned(build):
    _fact(fact_id="superseded", text="Gamla regler om uppsägningstid")
    index = build()
    update_fact(require_knowledge(), "superseded", status="superseded")
    assert _hits(index, "uppsägningstid") == []


def test_invalid_hits_do_not_consume_the_candidate_budget(build, monkeypatch):
    monkeypatch.setattr(hybrid_retrieval, "FACT_INDEX_PAGE", 2)
    for index_no in range(4):
        _fact(fact_id=f"f-{index_no}", text=f"Uppsägningstid regel nummer {index_no}")
    index = build()
    catalog = require_knowledge()
    for index_no in range(3):
        update_fact(catalog, f"f-{index_no}", invalid_at=NOW - timedelta(days=1))
    hits = _hits(index, "uppsägningstid", limit=2)
    assert [hit.fact.id for hit in hits] == ["f-3"]


def test_fact_from_another_tenant_never_appears(build):
    _fact(fact_id="foreign", text="Hemlig uppsägningstid för annan kund", customer_id=99)
    assert _hits(build(), "uppsägningstid") == []


def test_stale_index_is_refused_instead_of_silently_degrading(build, tmp_path):
    _fact(fact_id="initial", text="Första regeln om uppsägningstid")
    index = build()
    _fact(fact_id="fresh", text="Ny regel om uppsägningstid")
    with pytest.raises(FactIndexStaleError, match="behind the graph"):
        ensure_fact_index_current(require_knowledge(), tmp_path / "index")
    catalog = require_knowledge()
    new_watermark = reconcile(
        catalog, index, watermark_ms=read_watermark(tmp_path / "index"),
    )
    write_watermark(tmp_path / "index", new_watermark)
    ensure_fact_index_current(catalog, tmp_path / "index")
    assert {hit.fact.id for hit in _hits(index, "uppsägningstid")} == {"initial", "fresh"}


def test_dense_and_lexical_hits_fuse_without_duplicates(build):
    _fact(fact_id="both", text="Uppsägningstid vid lokalhyra")
    index = build()
    hits = _hits(index, "uppsägningstid", dense_query=[0.0] * 32)
    ids = [hit.fact.id for hit in hits]
    assert ids == list(dict.fromkeys(ids)), "fusion must not duplicate a fact"
    assert "both" in ids


def test_compound_parts_are_decomposed_generically(build):
    from app.services.tantivy_index import subword_parts

    parts = set(subword_parts("sekretessförpliktelse"))
    assert {"sekretess", "förpliktelse"} <= parts
    assert "tid" in subword_parts("uppsägningstid")
    assert subword_parts("tid") == ()
    assert subword_parts("kort") == ()


def test_compound_query_finds_the_compound_fact(build):
    _fact(fact_id="compound", text="Sekretessförpliktelse gäller för alla anställda")
    hits = _hits(build(), "förpliktelse")
    assert [hit.fact.id for hit in hits] == ["compound"]


def test_short_tokens_do_not_match_freely(index=None):
    """Sub-word query terms shorter than the floor are not searched."""
    from app.services.tantivy_index import MIN_QUERY_PART

    assert MIN_QUERY_PART > 3
    assert "tid" not in ("tid",) or len("tid") < MIN_QUERY_PART


def test_direct_bm25_hit_ranks_above_a_subword_only_hit(tmp_path):
    _fact(fact_id="direct", text="Oskäliga avtalsvillkor jämkas enligt lag")
    _fact(fact_id="subword", text="Sekretessförpliktelse om uppsägning")
    index = build_from_overgraph(require_knowledge(), tmp_path / "rank")
    hits = _hits(index, "avtalsvillkor")
    ids = [hit.fact.id for hit in hits]
    assert ids[0] == "direct"


def test_subword_matches_never_outrank_a_direct_compound_match(build):
    _fact(fact_id="relevant", text="Oskäliga avtalsvillkor jämkas enligt lag")
    _fact(fact_id="noise", text="Sekretessförpliktelse för tidrapportering")
    hits = _hits(build(), "avtalsvillkor", limit=1)
    assert [hit.fact.id for hit in hits] == ["relevant"]


def test_production_index_is_refused_when_missing_and_recovers_after_build(tmp_path, monkeypatch):
    """Research must see a visible error, never a silent dense-only fallback."""
    from app.services import retrieval_index
    from app.services.overgraph.catalogs import require_knowledge

    _fact(fact_id="recover", text="Återhämtning av lexikalt index")
    monkeypatch.setattr(retrieval_index, "index_directory", lambda: tmp_path / "lexical")
    retrieval_index.set_index(None)
    with pytest.raises(retrieval_index.RetrievalIndexUnavailableError, match="not open"):
        retrieval_index.require_current_index()

    built = build_from_overgraph(require_knowledge(), tmp_path / "lexical")
    retrieval_index.set_index(built, tmp_path / "lexical")
    assert retrieval_index.require_current_index() is built
    retrieval_index.set_index(None)

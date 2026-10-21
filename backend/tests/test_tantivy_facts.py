"""Tantivy indexes Fact nodes for lexical candidates; OverGraph stays authoritative."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services.knowledge.scope import customer_scope
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.labels import FACT
from app.services.overgraph.research import update_fact
from app.services.overgraph.write import upsert_entity, write_fact
from app.services.graph_v2.types import FactInput, NodeInput
from app.services.tantivy_index import (
    build_from_overgraph,
    pending_updates,
    read_watermark,
    reconcile,
)

CUSTOMER = 1


def _entity(key: str, customer_id: int = CUSTOMER) -> str:
    return upsert_entity(require_knowledge(), NodeInput(
        node_type="core.concept", name=key, scope=customer_scope(customer_id),
    )).key


def _fact(*, fact_id: str, text: str, customer_id: int = CUSTOMER) -> None:
    scope = customer_scope(customer_id)
    left, right = _entity(f"{fact_id}-subject", customer_id), _entity(f"{fact_id}-object", customer_id)
    write_fact(
        require_knowledge(),
        FactInput(
            source_id=left, target_id=right, scope=scope,
            predicate="legal.rule", fact_text=text, sources=(),
        ),
        key=fact_id,
    )


@pytest.fixture
def index_dir(tmp_path):
    return tmp_path / "index"


def _build(index_dir):
    return build_from_overgraph(require_knowledge(), index_dir)


def test_fact_nodes_are_lexically_searchable(index_dir):
    _fact(fact_id="fact-1", text="Avtalsvillkor får jämkas enligt 36 § avtalslagen")
    built = _build(index_dir)
    hits = built.search_fact_keys("jämkas", tenant_ids=(f"customer:{CUSTOMER}",))
    assert [hit.key for hit in hits] == ["fact-1"]
    assert hits[0].score > 0


def test_fact_search_is_tenant_isolated(index_dir):
    _fact(fact_id="fact-mine", text="Hemlig jämkningsregel för kund ett")
    _fact(fact_id="fact-other", text="Hemlig jämkningsregel för kund två", customer_id=2)
    built = _build(index_dir)
    mine = built.search_fact_keys("jämkningsregel", tenant_ids=(f"customer:{CUSTOMER}",))
    shared = built.search_fact_keys("jämkningsregel", tenant_ids=("shared",))
    assert [hit.key for hit in mine] == ["fact-mine"]
    assert shared == []


def test_lexical_hit_hydrates_to_the_authoritative_fact_with_its_validity(index_dir):
    _fact(fact_id="validity", text="Giltighetsfönster ska bevaras")
    catalog = require_knowledge()
    update_fact(catalog, "validity", invalid_at=datetime(2030, 1, 1, tzinfo=UTC))
    built = _build(index_dir)
    hits = built.search_fact_keys("giltighetsfönster", tenant_ids=(f"customer:{CUSTOMER}",))
    assert [hit.key for hit in hits] == ["validity"]
    row = catalog.get_by_key(FACT, hits[0].key)
    assert row is not None
    assert row.props["status"] == "active"
    assert int(row.props["invalid_at_ms"]) == int(datetime(2030, 1, 1, tzinfo=UTC).timestamp() * 1000)


def test_reconcile_indexes_facts_created_after_the_build(index_dir):
    _fact(fact_id="first", text="Första regeln om uppsägning")
    _build(index_dir)
    watermark = read_watermark(index_dir)
    _fact(fact_id="second", text="Andra regeln om uppsägning")
    assert pending_updates(require_knowledge(), watermark_ms=watermark) >= 1
    reopened = __import__("app.services.tantivy_index", fromlist=["TextUnitIndex"]).TextUnitIndex.open(
        index_dir / "current"
    )
    new_watermark = reconcile(require_knowledge(), reopened, watermark_ms=watermark)
    assert new_watermark > watermark
    hits = reopened.search_fact_keys("uppsägning", tenant_ids=(f"customer:{CUSTOMER}",))
    assert {hit.key for hit in hits} == {"first", "second"}


def test_rebuild_recovers_from_an_empty_index_directory(index_dir):
    _fact(fact_id="rebuild", text="Indexet kan byggas om från grafen")
    assert _build(index_dir) is not None
    rebuilt = _build(index_dir)
    hits = rebuilt.search_fact_keys("grafen", tenant_ids=(f"customer:{CUSTOMER}",))
    assert [hit.key for hit in hits] == ["rebuild"]


def test_index_rebuilds_from_source_anchored_fact_keys(index_dir):
    """After the identity change the index must be rebuildable from the graph alone."""
    from app.services.tantivy_index import INDEX_VERSION, read_index_version

    _fact(fact_id="first", text="Nio månaders uppsägningstid gäller.")
    _fact(fact_id="second", text="Nio månaders uppsägningstid gäller.")
    built = _build(index_dir)
    assert INDEX_VERSION == "graph-index-v4"
    assert read_index_version(index_dir) == INDEX_VERSION
    hits = built.search_fact_keys("uppsägningstid", tenant_ids=(f"customer:{CUSTOMER}",))
    assert {hit.key for hit in hits} == {"first", "second"}

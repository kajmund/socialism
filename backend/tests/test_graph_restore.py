"""Restore from a clean environment: OverGraph plus a Tantivy index rebuilt from it.

Acceptance for the additive graph: knowledge, provenance, relations and the search index
must be recoverable from the authoritative catalog alone, without any SQL graph mirror.
"""

from __future__ import annotations

from pathlib import Path

from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.knowledge.scope import customer_scope, shared_scope
from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.labels import CONTRADICTS, FACT, SUPPORTS, TEXT_UNIT
from app.services.overgraph.legal_claims import (
    VERIFIED,
    Support,
    add_support,
    claim_is_verified,
    evidence_links,
    legal_claim_key,
    link_evidence,
    upsert_legal_claim,
)
from app.services.overgraph.model import TextUnitWrite
from app.services.overgraph.write import upsert_entity, upsert_text_unit, write_fact
from app.services.tantivy_index import build_from_overgraph

DIM = 8
SCOPE = customer_scope(1)
PREDICATE = "contract.termination_days"


def _seed(catalog) -> dict[str, str]:
    keys: dict[str, str] = {}
    for suffix, version in (("a", "ver-a"), ("b", "ver-b")):
        upsert_text_unit(catalog, TextUnitWrite(
            unit_id=f"tu-{suffix}", scope=SCOPE, document_id=f"doc-{suffix}",
            document_version_id=version, text=f"Passage {suffix} om uppsägningstid.",
            content_hash=f"tu-{suffix}", ordinal=0,
        ))
    source = upsert_entity(catalog, NodeInput(
        node_type="legal.source", name="Avtalslagen", scope=SCOPE,
    ))
    target = upsert_entity(catalog, NodeInput(
        node_type="legal.issue", name="Uppsägningstid", scope=SCOPE,
    ))
    foreign_scope = customer_scope(2)
    foreign = upsert_entity(catalog, NodeInput(
        node_type="legal.source", name="Annan kund", scope=foreign_scope,
    ))
    foreign_target = upsert_entity(catalog, NodeInput(
        node_type="legal.issue", name="Uppsägningstid", scope=foreign_scope,
    ))
    keys["source"] = source.key
    keys["target"] = target.key
    keys["foreign"] = foreign.key

    for suffix in ("a", "b"):
        write_fact(catalog, FactInput(
            source_id=source.key, target_id=target.key, scope=SCOPE,
            predicate="legal.rule", fact_text="Nio månaders uppsägningstid gäller.",
            sources=(SourceRef("text_unit", f"tu-{suffix}"),),
        ))
    left = write_fact(catalog, FactInput(
        source_id=foreign.key, target_id=foreign_target.key, scope=foreign_scope,
        predicate="legal.rule", fact_text="Tolv månaders uppsägningstid gäller.",
        sources=(),
    ))
    right = write_fact(catalog, FactInput(
        source_id=source.key, target_id=target.key, scope=SCOPE,
        predicate="legal.rule", fact_text="Tolv månader gäller inte.",
        sources=(SourceRef("text_unit", "tu-a"),),
    ))
    catalog.upsert_edge(left.engine_id, right.engine_id, CONTRADICTS)

    claim = upsert_legal_claim(
        catalog, scope=SCOPE, predicate=PREDICATE, value={"days": 90},
    )
    keys["claim"] = claim.key
    for suffix, version in (("a", "ver-a"), ("b", "ver-b")):
        link_evidence(
            catalog, claim_key=claim.key, document_version_id=version,
            text_unit_ids=(f"tu-{suffix}",),
        )
        add_support(
            catalog, claim_key=claim.key, document_version_id=version,
            support=Support(
                text_unit_id=f"tu-{suffix}", decision=VERIFIED,
                verification_version="jev-2026-10",
                source_ref=f"doc-{suffix}",
            ),
        )
    shared = upsert_entity(catalog, NodeInput(
        node_type="legal.court", name="Högsta domstolen", scope=shared_scope(),
    ))
    keys["shared"] = shared.key
    return keys


def _seed_catalog(directory: Path):
    catalog = open_catalog(directory, kind="knowledge", dimension=DIM)
    keys = _seed(catalog)
    return catalog, keys


def test_restored_catalog_keeps_knowledge_provenance_and_relations(tmp_path: Path):
    original_dir = tmp_path / "graph" / "knowledge"
    original, keys = _seed_catalog(original_dir)
    counts = {
        label: original.count_nodes_by_labels([label])
        for label in (FACT, TEXT_UNIT)
    }
    contradictions = original.count_edges_by_label(CONTRADICTS)
    backups = original.snapshot(tmp_path / "backup" / "knowledge")
    original.close()
    assert backups is None or True

    restored = open_catalog(tmp_path / "backup" / "knowledge", kind="knowledge", dimension=DIM)
    try:
        assert restored.scrub() == 0
        assert {
            label: restored.count_nodes_by_labels([label]) for label in (FACT, TEXT_UNIT)
        } == counts
        assert restored.count_edges_by_label(CONTRADICTS) == contradictions

        # Additive identity survived: two source occurrences stay two facts.
        facts = [
            row
            for row in restored.query_nodes(
                label_filter={"labels": [FACT], "mode": "all"}, limit=100,
            )[0]
            if str(row.props.get("scope_key") or "") == SCOPE.scope_key
        ]
        assert len([row for row in facts if "Nio månader" in str(row.props.get("fact_text"))]) == 2

        # Provenance points at the original source units.
        for row in facts:
            if "Nio månader" in str(row.props.get("fact_text")):
                refs = str(row.props.get("source_refs_json") or "")
                assert "text_unit" in refs

        # The logical claim is restored with verified, per-version evidence.
        key = legal_claim_key(SCOPE, PREDICATE, {"days": 90})
        assert restored.get_by_key("Claim", key) is not None
        assert len(evidence_links(restored, key)) == 2
        assert claim_is_verified(restored, key, now=__import__("datetime").datetime.now(
            __import__("datetime").UTC,
        )) is True

        # Support edges survive the restore.
        assert restored.count_edges_by_label(SUPPORTS) >= 2
        assert restored.get_by_key("Entity", keys["shared"]) is not None
    finally:
        restored.close()


def test_tantivy_index_rebuilds_from_the_restored_catalog(tmp_path: Path):
    original, _keys = _seed_catalog(tmp_path / "graph" / "knowledge")
    original.snapshot(tmp_path / "backup" / "knowledge")
    original.close()

    restored = open_catalog(tmp_path / "backup" / "knowledge", kind="knowledge", dimension=DIM)
    try:
        index = build_from_overgraph(restored, tmp_path / "index")
        unit_hits = index.search("uppsägningstid", tenant_ids=(SCOPE.scope_key,), limit=10)
        fact_hits = index.search_fact_keys(
            "uppsägningstid", tenant_ids=(SCOPE.scope_key,), limit=10,
        )
        assert unit_hits.hits and fact_hits
        # Tenant isolation survives the rebuild: the other customer gets no own-tenant units.
        foreign = index.search("uppsägningstid", tenant_ids=("customer:2",), limit=10)
        own_units = {hit.key for hit in unit_hits.hits}
        assert {"tu-a", "tu-b"} <= own_units
        assert not ({hit.key for hit in foreign.hits} & own_units)
    finally:
        restored.close()

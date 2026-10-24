"""Differential test: direct ``write_fact`` and ``write_fact_via_owner`` land the
same fact semantics in two isolated catalogs with identical seed data.

Only non-semantic differences are normalized (owner receipts, created/recorded
timestamps, and the direction of the symmetric CONTRADICTS relation).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import tempfile
from pathlib import Path

import pytest

from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.model import TextUnitWrite
from app.services.overgraph.owner import OwnerClient, OvergraphOwner
from app.services.overgraph.owner_facts import write_fact_via_owner
from app.services.overgraph.write import upsert_entity, upsert_text_unit, write_fact
from tests.overgraph_graph_snapshot import graph_snapshot

DIMENSION = 4
VALID_AT = datetime(2025, 1, 1, tzinfo=UTC)
VOLATILE_FACT_PROPS = {"created_at_ms"}


def _seed(catalog):
    scope = customer_scope(1)
    source = upsert_entity(catalog, NodeInput(
        node_type="legal.source", name="Avtalslagen", scope=scope,
    ))
    target = upsert_entity(catalog, NodeInput(
        node_type="legal.issue", name="Uppsägningstid", scope=scope,
    ))
    context = upsert_entity(catalog, NodeInput(
        node_type="legal.context", name="Tjänst", scope=scope,
    ))
    for unit_id, ordinal in (("u1", 0), ("u2", 1)):
        upsert_text_unit(catalog, TextUnitWrite(
            unit_id=unit_id,
            scope=scope,
            document_id="doc-1",
            document_version_id="ver-1",
            text=f"TextUnit {unit_id}",
            content_hash=f"hash-{unit_id}",
            ordinal=ordinal,
        ))
    return scope, source.key, target.key, context.key


def _facts(keys):
    scope, source, target, context = keys
    first = FactInput(
        source_id=source,
        target_id=target,
        context_id=context,
        scope=scope,
        predicate="legal.rule",
        fact_text="Nio månaders uppsägningstid gäller.",
        sources=(
            SourceRef("text_unit", "u1"),
            SourceRef("text_unit", "u2"),
            SourceRef("episode", "ep-a"),
        ),
        occurrence_key="occ-a",
        valid_at=VALID_AT,
        embedding=tuple(0.25 for _ in range(DIMENSION)),
    )
    second = FactInput(
        source_id=source,
        target_id=target,
        scope=scope,
        predicate="legal.rule",
        fact_text="Avtalet förlängs årsvis.",
        sources=(SourceRef("text_unit", "u2"),),
        occurrence_key="occ-b",
    )
    rewritten = replace(
        first, sources=(*first.sources, SourceRef("episode", "ep-b")),
    )
    return first, second, rewritten


def _assert_props_equal(direct_props, owner_props):
    assert {
        key: value for key, value in direct_props.items()
        if key not in VOLATILE_FACT_PROPS
    } == {
        key: value for key, value in owner_props.items()
        if key not in VOLATILE_FACT_PROPS
    }


@pytest.fixture
def direct_catalog():
    root = Path(tempfile.mkdtemp(prefix="ogo-diff-"))
    catalog = open_catalog(root / "direct", kind="knowledge", dimension=DIMENSION)
    try:
        yield catalog, root
    finally:
        catalog.close()


async def test_direct_and_owner_fact_writes_are_semantically_identical(direct_catalog):
    direct, root = direct_catalog
    owner = OvergraphOwner(
        root / "owner", dimension=DIMENSION, socket_path=root / "owner.sock",
    )
    await owner.start()
    client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    try:
        direct_first, direct_second, direct_rewritten = _facts(_seed(direct))
        owner_first, owner_second, owner_rewritten = _facts(_seed(owner.catalog))

        direct_row = write_fact(direct, direct_first)
        owner_result = await write_fact_via_owner(client, owner_first)
        assert owner_result["key"] == direct_row.key
        _assert_props_equal(direct_row.props, owner_result["props"])

        direct_other = write_fact(direct, direct_second)
        owner_other = await write_fact_via_owner(client, owner_second)
        assert owner_other["key"] == direct_other.key

        write_fact(direct, direct_rewritten, contradiction_key=direct_other.key)
        rewritten = await write_fact_via_owner(
            client, owner_rewritten, contradiction_key=owner_other["key"],
        )
        assert rewritten["key"] == direct_row.key

        direct_snapshot = graph_snapshot(direct)
        owner_snapshot = graph_snapshot(owner.catalog)
        assert owner_snapshot == direct_snapshot
        _assert_temporal_and_provenance(direct_snapshot)
    finally:
        await owner.close()


def _assert_temporal_and_provenance(snapshot):
    edges = snapshot["edges"]
    subject_windows = {
        edge[3] for edge in edges if edge[1] == "SUBJECT"
    }
    assert int(VALID_AT.timestamp() * 1000) in subject_windows
    assert subject_windows <= {int(VALID_AT.timestamp() * 1000), "<created>"}
    support_refs = {
        dict(edge[2])["source_ref"] for edge in edges if edge[1] == "SUPPORTS"
    }
    assert support_refs == {"u1", "u2", "ep-a", "ep-b"}
    assert any(edge[1] == "CONTRADICTS" for edge in edges)

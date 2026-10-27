from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.services.graph_v2.types import FactInput, SourceRef
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.labels import ENTITY, FACT, scope_label
from app.services.overgraph.owner import OwnerClient, OvergraphOwner
from app.services.overgraph.owner_facts import write_fact_via_owner


@pytest.fixture
async def owner():
    root = Path(tempfile.mkdtemp(prefix="ogo-"))
    instance = OvergraphOwner(root / "catalog", dimension=4, socket_path=root / "owner.sock")
    await instance.start()
    try:
        yield instance
    finally:
        await instance.close()


async def test_fact_via_owner_writes_node_and_provenance(owner):
    scope = customer_scope(1)
    client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    await client.mutate("seed", {"upsert_nodes": [
        {"labels": [ENTITY, scope_label(scope.scope_key)], "key": "src", "props": {"scope_key": scope.scope_key}},
        {"labels": [ENTITY, scope_label(scope.scope_key)], "key": "dst", "props": {"scope_key": scope.scope_key}},
        {"labels": ["TextUnit", scope_label(scope.scope_key)], "key": "u1", "props": {"scope_key": scope.scope_key, "text": "x"}},
    ]}, kind="batch")
    proposed = FactInput(
        source_id="src", target_id="dst", scope=scope, predicate="legal.has",
        fact_text="Avtalet har uppsägningstid.", sources=(SourceRef(kind="text_unit", ref="u1"),),
    )
    result = await write_fact_via_owner(client, proposed, mutation_id="fact-op-1")
    assert result["result"]["ok"] is True
    row = owner.catalog.get_by_key(FACT, result["key"])
    assert row is not None
    assert "u1" in row.props["source_refs_json"]

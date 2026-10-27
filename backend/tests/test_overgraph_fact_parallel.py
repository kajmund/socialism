from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from app.services.graph_v2.types import FactInput, SourceRef
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.labels import ENTITY, FACT, scope_label
from app.services.overgraph.owner import OwnerClient, OvergraphOwner
from app.services.overgraph.owner_facts import write_fact_via_owner


def _nodes(scope, units):
    return [
        {"labels": [ENTITY, scope_label(scope.scope_key)], "key": "src", "props": {"scope_key": scope.scope_key, "node_type": "org", "name": "src"}},
        {"labels": [ENTITY, scope_label(scope.scope_key)], "key": "dst", "props": {"scope_key": scope.scope_key, "node_type": "org", "name": "dst"}},
    ] + [{"labels": ["TextUnit", scope_label(scope.scope_key)], "key": unit, "props": {"scope_key": scope.scope_key, "text": "t", "content_hash": unit, "document_id": "d", "document_version_id": "v"}} for unit in units]


def _fact(scope, extra):
    return FactInput(source_id="src", target_id="dst", scope=scope, predicate="legal.has", fact_text="Avtalet har uppsägningstid.", sources=(SourceRef(kind="text_unit", ref="u0"), SourceRef(kind="text_unit", ref=extra)))


async def test_parallel_evidence_keeps_both_sources():
    scope = customer_scope(1)
    root = Path(tempfile.mkdtemp(prefix="fact-"))
    owner = OvergraphOwner(root / "owner", dimension=4, socket_path=root / "s.sock")
    await owner.start()
    barrier = asyncio.Barrier(2)
    state = {"gate": False, "count": 0}

    class GateClient(OwnerClient):
        async def mutate(self, mutation_id, patch, *, kind="patch"):
            if state["gate"] and kind == "batch" and mutation_id != "seed" and state["count"] < 2:
                state["count"] += 1
                await barrier.wait()
            return await super().mutate(mutation_id, patch, kind=kind)

    client = GateClient(owner.socket_path, catalog_id=owner.catalog_id)
    try:
        await client.mutate("seed", {"upsert_nodes": _nodes(scope, ["u0", "ux", "uy"])}, kind="batch")
        conflicts: list[int] = []
        state["gate"] = True
        await asyncio.gather(
            write_fact_via_owner(client, _fact(scope, "ux"), on_conflict=lambda: conflicts.append(1)),
            write_fact_via_owner(client, _fact(scope, "uy"), on_conflict=lambda: conflicts.append(1)),
        )
        assert conflicts, "second merge must be rejected by a stale precondition"
        # Resolve final fact key by writing once more (idempotent no-op).
        result = await write_fact_via_owner(client, _fact(scope, "ux"))
        row = owner.catalog.get_by_key(FACT, result["key"])
        refs = {item["ref"] for item in json.loads(str(row.props["source_refs_json"]))}
        assert {"u0", "ux", "uy"} <= refs
    finally:
        await owner.close()


async def test_direct_and_owner_fact_parity():
    from app.services.overgraph.catalogs import open_catalog
    from app.services.overgraph.write import write_fact

    scope = customer_scope(1)
    root = Path(tempfile.mkdtemp(prefix="fact-"))
    direct = open_catalog(root / "direct", kind="knowledge", dimension=4)
    owner = OvergraphOwner(root / "owner", dimension=4, socket_path=root / "s.sock")
    await owner.start()
    client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    try:
        direct.graph_patch(upsert_nodes=_nodes(scope, ["u0", "ux"]))
        await client.mutate("seed", {"upsert_nodes": _nodes(scope, ["u0", "ux"])}, kind="batch")
        direct_row = write_fact(direct, _fact(scope, "ux"))
        owner_row = owner.catalog.get_by_key(FACT, (await write_fact_via_owner(client, _fact(scope, "ux")))["key"])
        assert direct_row.key == owner_row.key
        for prop in ("predicate", "fact_text", "status", "scope_key", "valid_at_ms", "invalid_at_ms"):
            assert direct_row.props.get(prop) == owner_row.props.get(prop)
        direct_refs = {item["ref"] for item in json.loads(str(direct_row.props["source_refs_json"]))}
        owner_refs = {item["ref"] for item in json.loads(str(owner_row.props["source_refs_json"]))}
        assert direct_refs == owner_refs
    finally:
        direct.close()
        await owner.close()

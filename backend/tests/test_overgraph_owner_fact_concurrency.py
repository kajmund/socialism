"""Deterministic concurrency test for the owner-backed fact merge.

Two writers read the same original fact revision, synchronize after the read and
before the mutation (one-shot barrier; seed operations never touch it), then one
must lose its precondition and re-read. The final fact keeps every provenance
source and SUPPORTS edge.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from app.services.graph_v2.types import FactInput, SourceRef
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.labels import ENTITY, FACT, SUPPORTS, scope_label
from app.services.overgraph.owner import OwnerClient, OvergraphOwner
from app.services.overgraph.owner_facts import write_fact_via_owner

DIMENSION = 4
TIMEOUT_SECONDS = 20


def _seed_nodes(scope, units):
    return [
        {
            "labels": [ENTITY, scope_label(scope.scope_key)],
            "key": "src",
            "props": {"scope_key": scope.scope_key, "node_type": "org", "name": "src"},
        },
        {
            "labels": [ENTITY, scope_label(scope.scope_key)],
            "key": "dst",
            "props": {"scope_key": scope.scope_key, "node_type": "org", "name": "dst"},
        },
        *[
            {
                "labels": ["TextUnit", scope_label(scope.scope_key)],
                "key": unit,
                "props": {
                    "scope_key": scope.scope_key,
                    "text": f"text {unit}",
                    "content_hash": unit,
                    "document_id": "doc",
                    "document_version_id": "ver",
                },
            }
            for unit in units
        ],
    ]


def _fact(scope, extra: str) -> FactInput:
    return FactInput(
        source_id="src",
        target_id="dst",
        scope=scope,
        predicate="legal.has",
        fact_text="Avtalet har uppsägningstid.",
        sources=(SourceRef("text_unit", "u0"), SourceRef("text_unit", extra)),
        occurrence_key="occ",
    )


def _fact_node(patch):
    return next(node for node in patch["upsert_nodes"] if FACT in node["labels"])


def _expected_facts(patch):
    return [
        node for node in patch.get("expected_nodes", ())
        if node.get("label") == FACT
    ]


class BarrierClient(OwnerClient):
    """One-shot barrier between the read and the first mutation of each writer."""

    def __init__(self, socket_path: Path, *, catalog_id: str) -> None:
        super().__init__(socket_path, catalog_id=catalog_id)
        self.gate_open = False
        self.barrier: asyncio.Barrier | None = None
        self.slots = 0
        self.calls: list[dict] = []

    async def mutate(self, mutation_id, patch, *, kind="patch"):
        if mutation_id.startswith("seed"):
            return await super().mutate(mutation_id, patch, kind=kind)
        gated = self.gate_open and self.slots > 0
        if gated:
            self.slots -= 1
        self.calls.append({
            "task": asyncio.current_task().get_name(),
            "mutation_id": mutation_id,
            "patch": patch,
            "gated": gated,
        })
        if gated:
            assert self.barrier is not None
            await asyncio.wait_for(self.barrier.wait(), timeout=TIMEOUT_SECONDS)
        return await super().mutate(mutation_id, patch, kind=kind)


async def test_parallel_provenance_merge_loses_one_precondition_and_rereads():
    scope = customer_scope(1)
    root = Path(tempfile.mkdtemp(prefix="ogo-race-"))
    owner = OvergraphOwner(
        root / "owner", dimension=DIMENSION, socket_path=root / "owner.sock",
    )
    await owner.start()
    client = BarrierClient(owner.socket_path, catalog_id=owner.catalog_id)
    try:
        await client.mutate(
            "seed-nodes", {"upsert_nodes": _seed_nodes(scope, ["u0", "ux", "uy"])},
            kind="batch",
        )
        seed_fact = await write_fact_via_owner(
            client,
            FactInput(
                source_id="src", target_id="dst", scope=scope,
                predicate="legal.has", fact_text="Avtalet har uppsägningstid.",
                sources=(SourceRef("text_unit", "u0"),), occurrence_key="occ",
            ),
            mutation_id="seed-fact",
        )
        assert seed_fact["result"]["ok"] is True
        conflicts: list[int] = []
        client.gate_open = True
        client.barrier = asyncio.Barrier(2)
        client.slots = 2
        tasks = [
            asyncio.create_task(
                write_fact_via_owner(
                    client, _fact(scope, unit), on_conflict=lambda: conflicts.append(1),
                ),
                name=unit,
            )
            for unit in ("ux", "uy")
        ]
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=TIMEOUT_SECONDS)

        assert len(conflicts) == 1, "exactly one writer must lose its precondition"
        assert all(result["result"]["ok"] is True for result in results)
        assert results[0]["key"] == results[1]["key"] == seed_fact["key"]

        first_attempts = [call for call in client.calls if call["gated"]]
        assert len(first_attempts) == 2
        assert {call["task"] for call in first_attempts} == {"ux", "uy"}
        keys = {_fact_node(call["patch"])["key"] for call in first_attempts}
        assert keys == {seed_fact["key"]}
        revision = json.dumps(
            [{"kind": "text_unit", "ref": "u0"}], ensure_ascii=False,
        )
        for call in first_attempts:
            expected = _expected_facts(call["patch"])[0]
            assert expected["props"]["source_refs_json"] == revision, (
                "both writers must read the same original fact revision"
            )

        retries = [
            call for call in client.calls
            if not call["gated"] and call["task"] in {"ux", "uy"}
        ]
        assert retries, "the losing writer must retry after the precondition conflict"
        assert retries[0]["mutation_id"] != next(
            call["mutation_id"] for call in first_attempts
            if call["task"] == retries[0]["task"]
        )
        retry_refs = {
            item["ref"] for item in json.loads(
                _fact_node(retries[0]["patch"])["props"]["source_refs_json"]
            )
        }
        assert retry_refs == {"u0", "ux", "uy"}
        assert retries[0]["patch"].get("expected_nodes") is not None

        final = owner.catalog.get_by_key(FACT, seed_fact["key"])
        assert final is not None
        refs = {item["ref"] for item in json.loads(final.props["source_refs_json"])}
        assert refs == {"u0", "ux", "uy"}
        for unit in ("u0", "ux", "uy"):
            unit_row = owner.catalog.get_by_key("TextUnit", unit)
            assert unit_row is not None and unit_row.engine_id is not None
            assert owner.catalog.get_edge_by_triple(
                unit_row.engine_id, final.engine_id, SUPPORTS,
            ) is not None
    finally:
        await owner.close()

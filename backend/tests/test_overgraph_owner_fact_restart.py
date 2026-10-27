"""Transport retry vs. merge retry for owner-backed fact writes.

A transport retry replays the exact same mutation id and payload and must return
the persisted receipt after the owner restarts, without writing twice. A retry
after a precondition conflict is a *new* merge attempt with a new mutation id
(covered deterministically in test_overgraph_owner_fact_concurrency.py).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.services.graph_v2.types import FactInput, SourceRef
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.labels import ENTITY, FACT, SUPPORTS, scope_label
from app.services.overgraph.owner import (
    OwnerClient,
    OwnerUnavailable,
    OvergraphOwner,
)
from app.services.overgraph.owner_facts import write_fact_via_owner

DIMENSION = 4


def _seed_nodes(scope):
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
        {
            "labels": ["TextUnit", scope_label(scope.scope_key)],
            "key": "u0",
            "props": {
                "scope_key": scope.scope_key,
                "text": "text u0",
                "content_hash": "u0",
                "document_id": "doc",
                "document_version_id": "ver",
            },
        },
    ]


def _fact(scope) -> FactInput:
    return FactInput(
        source_id="src",
        target_id="dst",
        scope=scope,
        predicate="legal.has",
        fact_text="Avtalet har uppsägningstid.",
        sources=(SourceRef("text_unit", "u0"),),
        occurrence_key="occ",
    )


class LostResponseClient(OwnerClient):
    """Commit the mutation, then behave as if the response never arrived."""

    def __init__(self, socket_path: Path, *, catalog_id: str) -> None:
        super().__init__(socket_path, catalog_id=catalog_id)
        self.sent: list[tuple[str, dict, str]] = []

    async def mutate(self, mutation_id, patch, *, kind="patch"):
        if mutation_id.startswith("fact-lost"):
            self.sent.append((mutation_id, patch, kind))
            await super().mutate(mutation_id, patch, kind=kind)
            raise OwnerUnavailable("response lost after commit")
        return await super().mutate(mutation_id, patch, kind=kind)


async def test_transport_retry_replays_same_receipt_after_owner_restart():
    scope = customer_scope(1)
    root = Path(tempfile.mkdtemp(prefix="ogo-restart-"))
    socket_path = root / "owner.sock"
    owner = OvergraphOwner(root / "owner", dimension=DIMENSION, socket_path=socket_path)
    await owner.start()
    try:
        seed = OwnerClient(socket_path, catalog_id=owner.catalog_id)
        await seed.mutate("seed-nodes", {"upsert_nodes": _seed_nodes(scope)}, kind="batch")
        lost = LostResponseClient(socket_path, catalog_id=owner.catalog_id)
        with pytest.raises(OwnerUnavailable):
            await write_fact_via_owner(lost, _fact(scope), mutation_id="fact-lost-1")
        assert lost.sent, "the mutation must reach the owner before the response is lost"
        first_id, first_patch, first_kind = lost.sent[0]
        assert all(
            (mutation_id, patch, kind) == (first_id, first_patch, first_kind)
            for mutation_id, patch, kind in lost.sent
        ), "transport retry must replay the same id and payload"
        committed_key = next(
            node["key"] for node in first_patch["upsert_nodes"]
            if FACT in node["labels"]
        )
    finally:
        await owner.close()

    restarted = OvergraphOwner(
        root / "owner", dimension=DIMENSION, socket_path=socket_path,
    )
    await restarted.start()
    try:
        replay = OwnerClient(socket_path, catalog_id=restarted.catalog_id)
        result = await replay.mutate(first_id, first_patch, kind=first_kind)
        assert result["ok"] is True
        assert result.get("duplicate") is True
        catalog = restarted.catalog
        assert catalog.count_nodes_by_labels([FACT]) == 1
        assert catalog.count_edges_by_label(SUPPORTS) == 1
        fact = catalog.get_by_key(FACT, committed_key)
        assert fact is not None
        receipt = catalog.get_by_key("MutationReceipt", first_id)
        assert receipt is not None
    finally:
        await restarted.close()

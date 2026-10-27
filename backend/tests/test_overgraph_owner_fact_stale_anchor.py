"""A concurrent TextUnit re-ingest must move the fact to the new version anchor.

The first attempt reads version v1 and is rejected by the TextUnit precondition
after the unit moved to v2. The retry re-reads the anchor, computes the v2 fact
key and writes one fact under that new key.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.services.graph_v2.types import FactInput, SourceRef
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.labels import ENTITY, FACT, TEXT_UNIT, scope_label
from app.services.overgraph.owner import OwnerClient, OvergraphOwner
from app.services.overgraph.owner_facts import write_fact_via_owner
from app.services.overgraph.write import fact_key_from_anchor

DIMENSION = 4


def _unit_node(version: str) -> dict:
    return {
        "labels": [TEXT_UNIT, scope_label("customer:1")],
        "key": "u1",
        "props": {
            "scope_key": "customer:1",
            "text": "text",
            "content_hash": "h1",
            "document_id": "doc",
            "document_version_id": version,
        },
    }


def _seed(scope):
    return {
        "upsert_nodes": [
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
            _unit_node("v1"),
        ]
    }


class ReingestBetweenReadAndWrite(OwnerClient):
    """Move the source TextUnit to a new version on the first fact attempt."""

    def __init__(self, socket_path: Path, *, catalog_id: str) -> None:
        super().__init__(socket_path, catalog_id=catalog_id)
        self.reingested = False
        self.patches: list[dict] = []

    async def mutate(self, mutation_id, patch, *, kind="patch"):
        if mutation_id.startswith("fact:") and not self.reingested:
            self.reingested = True
            self.patches.append(patch)
            await super().mutate(
                "seed-reingest", {"upsert_nodes": [_unit_node("v2")]}, kind="batch",
            )
        elif mutation_id.startswith("fact:"):
            self.patches.append(patch)
        return await super().mutate(mutation_id, patch, kind=kind)


async def test_stale_anchor_is_reread_and_fact_moves_to_new_version():
    scope = customer_scope(1)
    root = Path(tempfile.mkdtemp(prefix="ogo-anchor-"))
    owner = OvergraphOwner(
        root / "owner", dimension=DIMENSION, socket_path=root / "owner.sock",
    )
    await owner.start()
    client = ReingestBetweenReadAndWrite(
        owner.socket_path, catalog_id=owner.catalog_id,
    )
    try:
        await client.mutate("seed-nodes", _seed(scope), kind="batch")
        proposed = FactInput(
            source_id="src",
            target_id="dst",
            scope=scope,
            predicate="legal.has",
            fact_text="Avtalet har uppsägningstid.",
            sources=(SourceRef("text_unit", "u1"),),
            occurrence_key="occ",
        )
        conflicts: list[int] = []
        result = await write_fact_via_owner(
            client, proposed, on_conflict=lambda: conflicts.append(1),
        )
        assert conflicts == [1], "the stale v1 anchor must fail the precondition"
        assert len(client.patches) == 2, "the retry must build a new merge attempt"
        v1_expected = next(
            node for node in client.patches[0]["expected_nodes"]
            if node["label"] == TEXT_UNIT
        )
        v2_expected = next(
            node for node in client.patches[1]["expected_nodes"]
            if node["label"] == TEXT_UNIT
        )
        assert v1_expected["props"]["document_version_id"] == "v1"
        assert v2_expected["props"]["document_version_id"] == "v2"

        def key_for(version: str) -> str:
            return fact_key_from_anchor(proposed, (version, "u1"))

        assert result["key"] == key_for("v2")
        catalog = owner.catalog
        assert catalog.get_by_key(FACT, key_for("v1")) is None
        assert catalog.get_by_key(FACT, result["key"]) is not None
        assert catalog.count_nodes_by_labels([FACT]) == 1
    finally:
        await owner.close()

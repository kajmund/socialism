"""Durable generation/tombstone ledger for the derived Tantivy index."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.labels import FACT, TEXT_UNIT, scope_label
from app.services.overgraph.owner import OvergraphOwner, OwnerClient
from app.services.tantivy_generation import (
    SearchChange,
    SearchIndexer,
    SearchIndexLagError,
    SearchIndexRebuildRequired,
    append_changes,
    ensure_generation,
    read_checkpoint,
    read_generation,
    write_checkpoint,
)
from app.services.tantivy_index import build_from_overgraph

DIMENSION = 4
SCOPE = "customer:1"


async def _start():
    root = Path(tempfile.mkdtemp(prefix="tantivy-ledger-"))
    catalog = open_catalog(root / "catalog", kind="knowledge", dimension=DIMENSION)
    owner = OvergraphOwner(root / "catalog", dimension=DIMENSION,
                           socket_path=root / "owner.sock", catalog=catalog)
    await owner.start()
    client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    seed = [{
        "labels": [TEXT_UNIT, scope_label(SCOPE)], "key": "u-old",
        "props": {
            "scope_key": SCOPE, "document_id": "doc", "document_version_id": "v1",
            "content_hash": "h-old", "text": "uppsagning gammal", "section_id": "s1",
        },
    }, {
        "labels": [FACT, scope_label(SCOPE)], "key": "f-old",
        "props": {
            "scope_key": SCOPE, "status": "active", "normalized_text": "uppsagning faktum",
            "valid_at_ms": 0, "invalid_at_ms": 0,
        },
    }]
    await client.mutate("seed", {"upsert_nodes": seed}, kind="batch")
    index_dir = root / "tantivy"
    index = build_from_overgraph(catalog, index_dir)
    checkpoint = root / "checkpoint.json"
    await ensure_generation(client)
    write_checkpoint(checkpoint, await read_generation(client))
    return owner, client, index, checkpoint, root


async def test_text_unit_delete_is_removed_from_index():
    owner, client, index, checkpoint, _root = await _start()
    try:
        assert index.search("uppsagning").hits
        await append_changes(
            client, [SearchChange("text_unit", "delete", "u-old")],
            mutation_id="delete-u-old",
        )
        indexer = SearchIndexer(index, checkpoint)
        await indexer.apply_pending(client)
        assert "u-old" not in {hit.key for hit in index.search("uppsagning").hits}
        assert read_checkpoint(checkpoint) == await read_generation(client)
    finally:
        await owner.close()


async def test_reingest_replaces_old_version_document():
    owner, client, index, checkpoint, _root = await _start()
    try:
        await append_changes(client, [
            SearchChange("text_unit", "delete", "u-old"),
            SearchChange("text_unit", "upsert", "u-new", document_version_id="v2"),
        ], mutation_id="reingest")
        row = [{
            "labels": [TEXT_UNIT, scope_label(SCOPE)], "key": "u-new",
            "props": {
                "scope_key": SCOPE, "document_id": "doc", "document_version_id": "v2",
                "content_hash": "h-new", "text": "uppsagning ny", "section_id": "s1",
            },
        }]
        await client.mutate("add-u-new", {"upsert_nodes": row}, kind="batch")
        indexer = SearchIndexer(index, checkpoint)
        await indexer.apply_pending(client)
        keys = {hit.key for hit in index.search("uppsagning").hits}
        assert "u-old" not in keys and "u-new" in keys
    finally:
        await owner.close()


async def test_indexer_crash_replays_without_losing_or_duplicating():
    owner, client, index, checkpoint, _root = await _start()
    try:
        row = [{
            "labels": [TEXT_UNIT, scope_label(SCOPE)], "key": "u-crash",
            "props": {
                "scope_key": SCOPE, "document_id": "doc", "document_version_id": "v2",
                "content_hash": "h-crash", "text": "uppsagning krasch", "section_id": "s1",
            },
        }]
        await client.mutate("add-u-crash", {"upsert_nodes": row}, kind="batch")
        await append_changes(
            client, [SearchChange("text_unit", "upsert", "u-crash")],
            mutation_id="crash-upsert",
        )
        generation = await read_generation(client)
        indexer = SearchIndexer(index, checkpoint)
        # Simulate a crash after the Tantivy write but before the checkpoint.
        await indexer._apply_generation(client, generation)
        assert read_checkpoint(checkpoint) == generation - 1
        reopened = SearchIndexer(index, checkpoint)
        await reopened.apply_pending(client)
        hits = [hit for hit in index.search("uppsagning").hits if hit.key == "u-crash"]
        assert len(hits) == 1
        assert read_checkpoint(checkpoint) == generation
    finally:
        await owner.close()


async def test_lag_is_detected_and_caught_up():
    owner, client, index, checkpoint, _root = await _start()
    try:
        for number in range(3):
            row = [{
                "labels": [TEXT_UNIT, scope_label(SCOPE)], "key": f"u-lag-{number}",
                "props": {
                    "scope_key": SCOPE, "document_id": "doc",
                    "document_version_id": f"v{number + 2}", "content_hash": f"h{number}",
                    "text": f"uppsagning lag {number}", "section_id": "s1",
                },
            }]
            await client.mutate(f"add-lag-{number}", {"upsert_nodes": row}, kind="batch")
            await append_changes(
                client, [SearchChange("text_unit", "upsert", f"u-lag-{number}")],
                mutation_id=f"lag-{number}",
            )
        indexer = SearchIndexer(index, checkpoint)
        assert await indexer.lag(client) == 3
        with pytest.raises(SearchIndexLagError):
            await indexer.assert_current(client)
        await indexer.apply_pending(client)
        assert await indexer.lag(client) == 0
    finally:
        await owner.close()


async def test_checkpoint_ahead_requires_rebuild_and_rebuild_uses_current_graph():
    owner, client, index, checkpoint, root = await _start()
    try:
        write_checkpoint(checkpoint, await read_generation(client) + 1)
        indexer = SearchIndexer(index, checkpoint)
        with pytest.raises(SearchIndexRebuildRequired):
            await indexer.apply_pending(client)
        row = await client.read([{"label": TEXT_UNIT, "key": "u-old"}])
        assert row["values"]
        # Rebuild deterministically from the authoritative graph.
        generation = await read_generation(client)
        rebuilt = indexer.rebuild_from(owner.catalog, root / "tantivy", generation=generation)
        assert read_checkpoint(checkpoint) == generation
        assert rebuilt.search("uppsagning").hits
    finally:
        await owner.close()

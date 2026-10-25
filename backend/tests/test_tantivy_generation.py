"""Durable generation/tombstone ledger for the derived Tantivy index."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.labels import FACT, TEXT_UNIT, scope_label
from app.services.overgraph.owner import OvergraphOwner, OwnerClient
from app.services.tantivy_generation import (
    SearchIndexer,
    SearchIndexLagError,
    SearchIndexRebuildRequired,
    read_checkpoint,
    read_generation,
    validate_candidates,
    write_checkpoint,
)
from app.services.tantivy_index import build_from_overgraph

DIMENSION = 4
SCOPE = "customer:1"


def _unit(key: str, version: str = "v1", text: str = "uppsagning gammal") -> dict:
    return {
        "labels": [TEXT_UNIT, scope_label(SCOPE)], "key": key,
        "props": {
            "scope_key": SCOPE, "document_id": "doc", "document_version_id": version,
            "content_hash": f"h-{key}-{version}", "text": text, "section_id": "s1",
        },
    }


def _fact(key: str, *, status: str = "active") -> dict:
    return {
        "labels": [FACT, scope_label(SCOPE)], "key": key,
        "props": {
            "scope_key": SCOPE, "status": status, "normalized_text": "uppsagning faktum",
            "valid_at_ms": 0, "invalid_at_ms": 0,
        },
    }


async def _start():
    root = Path(tempfile.mkdtemp(prefix="tantivy-ledger-"))
    catalog = open_catalog(root / "catalog", kind="knowledge", dimension=DIMENSION)
    owner = OvergraphOwner(root / "catalog", dimension=DIMENSION,
                           socket_path=root / "owner.sock", catalog=catalog)
    await owner.start()
    client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    await client.mutate("seed", {"upsert_nodes": [
        _unit("u-old"), _fact("f-old"),
    ]}, kind="batch")
    index_dir = root / "tantivy"
    index = build_from_overgraph(catalog, index_dir)
    checkpoint = root / "checkpoint.json"
    write_checkpoint(checkpoint, await read_generation(client))
    return owner, client, index, checkpoint, root


async def test_ingest_is_searchable_and_delete_removes_it():
    owner, client, index, checkpoint, _root = await _start()
    try:
        assert "u-old" in {hit.key for hit in index.search("uppsagning").hits}
        await client.mutate(
            "delete-u-old",
            {"delete_nodes": [{"label": TEXT_UNIT, "key": "u-old"}]},
            kind="batch",
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
        await client.mutate("reingest", {
            "delete_nodes": [{"label": TEXT_UNIT, "key": "u-old"}],
            "upsert_nodes": [_unit("u-new", "v2", "uppsagning ny")],
        }, kind="batch")
        indexer = SearchIndexer(index, checkpoint)
        await indexer.apply_pending(client)
        keys = {hit.key for hit in index.search("uppsagning").hits}
        assert "u-old" not in keys and "u-new" in keys
    finally:
        await owner.close()


async def test_fact_revocation_is_removed_from_index():
    owner, client, index, checkpoint, _root = await _start()
    try:
        assert "f-old" in {hit.key for hit in index.search_fact_keys(
            "uppsagning", tenant_ids=(SCOPE,), limit=10,
        )}
        await client.mutate(
            "revoke-fact", {"upsert_nodes": [_fact("f-old", status="revoked")]},
            kind="batch",
        )
        indexer = SearchIndexer(index, checkpoint)
        await indexer.apply_pending(client)
        assert "f-old" not in {hit.key for hit in index.search_fact_keys(
            "uppsagning", tenant_ids=(SCOPE,), limit=10,
        )}
    finally:
        await owner.close()


async def test_indexer_crash_replays_without_losing_or_duplicating():
    owner, client, index, checkpoint, _root = await _start()
    try:
        await client.mutate(
            "add-u-crash", {"upsert_nodes": [_unit("u-crash", "v2", "uppsagning krasch")]},
            kind="batch",
        )
        generation = await read_generation(client)
        indexer = SearchIndexer(index, checkpoint)
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
            await client.mutate(
                f"add-lag-{number}",
                {"upsert_nodes": [_unit(f"u-lag-{number}", f"v{number + 2}")]},
                kind="batch",
            )
        indexer = SearchIndexer(index, checkpoint)
        assert await indexer.lag(client) == 3
        with pytest.raises(SearchIndexLagError):
            await indexer.assert_current(client)
        await indexer.apply_pending(client)
        assert await indexer.lag(client) == 0
    finally:
        await owner.close()


async def test_checkpoint_ahead_requires_rebuild():
    owner, client, index, checkpoint, root = await _start()
    try:
        write_checkpoint(checkpoint, await read_generation(client) + 1)
        indexer = SearchIndexer(index, checkpoint)
        with pytest.raises(SearchIndexRebuildRequired):
            await indexer.apply_pending(client)
        generation = await read_generation(client)
        rebuilt = indexer.rebuild_from(owner.catalog, root / "tantivy", generation=generation)
        assert read_checkpoint(checkpoint) == generation
        assert rebuilt.search("uppsagning").hits
    finally:
        await owner.close()


async def test_duplicate_and_failed_mutations_do_not_bump_generation():
    owner, client, index, checkpoint, _root = await _start()
    try:
        before = await read_generation(client)
        patch = {"upsert_nodes": [_unit("u-duplicate")]}
        first = await client.mutate("duplicate-id", patch, kind="batch")
        second = await client.mutate("duplicate-id", patch, kind="batch")
        assert first["ok"] is True and second["duplicate"] is True
        assert await read_generation(client) == before + 1

        failed = await client.mutate("failed-mutation", {
            "upsert_nodes": [_unit("u-failed")],
            "upsert_edges": [{
                "from": {"label": TEXT_UNIT, "key": "u-failed"},
                "to": {"label": TEXT_UNIT, "key": "missing"},
                "label": "NEXT",
            }],
        }, kind="batch")
        assert failed["ok"] is False
        assert await read_generation(client) == before + 1
        indexer = SearchIndexer(index, checkpoint)
        await indexer.apply_pending(client)
        assert read_checkpoint(checkpoint) == before + 1
    finally:
        await owner.close()


async def test_owner_restart_preserves_generation_history():
    owner, client, index, checkpoint, root = await _start()
    owner_closed = False
    try:
        await client.mutate(
            "before-restart", {"upsert_nodes": [_unit("u-restart", "v2")]},
            kind="batch",
        )
        generation = await read_generation(client)
        await owner.close()
        owner_closed = True
        catalog = open_catalog(root / "catalog", kind="knowledge", dimension=DIMENSION)
        restarted = OvergraphOwner(root / "catalog", dimension=DIMENSION,
                                  socket_path=root / "owner.sock", catalog=catalog)
        await restarted.start()
        restarted_client = OwnerClient(restarted.socket_path, catalog_id=restarted.catalog_id)
        try:
            assert await read_generation(restarted_client) == generation
            indexer = SearchIndexer(index, checkpoint)
            await indexer.apply_pending(restarted_client)
            assert "u-restart" in {hit.key for hit in index.search("uppsagning").hits}
        finally:
            await restarted.close()
    finally:
        if not owner_closed:
            await owner.close()


async def test_non_search_change_does_not_bump_generation():
    owner, client, index, checkpoint, _root = await _start()
    try:
        before = await read_generation(client)
        await client.mutate("entity-only", {"upsert_nodes": [{
            "labels": ["Entity", scope_label(SCOPE)], "key": "entity-only",
            "props": {"scope_key": SCOPE, "node_type": "legal.source"},
        }]}, kind="batch")
        assert await read_generation(client) == before
    finally:
        await owner.close()


async def test_paginated_replay_handles_a_large_generation():
    owner, client, index, checkpoint, _root = await _start()
    try:
        nodes = [_unit(f"bulk-{number}", f"v{number + 2}", f"uppsagning bulk {number}")
                 for number in range(1100)]
        await client.mutate("bulk-1100", {"upsert_nodes": nodes}, kind="batch")
        indexer = SearchIndexer(index, checkpoint, page_size=100)
        await indexer.apply_pending(client)
        assert await indexer.lag(client) == 0
        result = index.search("uppsagning", kind="text_unit", limit=1)
        # 1100 bulk units plus the original u-old.
        assert result.total == 1101
    finally:
        await owner.close()


async def test_validation_rejects_stale_deleted_and_revoked_candidates():
    owner, client, index, checkpoint, _root = await _start()
    try:
        await client.mutate("stale-delete", {
            "delete_nodes": [{"label": TEXT_UNIT, "key": "u-old"}],
            "upsert_nodes": [_fact("f-old", status="revoked")],
        }, kind="batch")
        # The index has not applied the generation yet: stale hits still exist.
        stale_units = {hit.key for hit in index.search("uppsagning").hits}
        assert "u-old" in stale_units
        valid = await validate_candidates(
            client, text_unit_keys=["u-old"], fact_keys=["f-old"],
        )
        assert valid == set()
        indexer = SearchIndexer(index, checkpoint)
        await indexer.ensure_current(client)
        assert "u-old" not in {hit.key for hit in index.search("uppsagning").hits}
        assert "f-old" not in {hit.key for hit in index.search_fact_keys(
            "uppsagning", tenant_ids=(SCOPE,), limit=10,
        )}
    finally:
        await owner.close()


async def test_restart_resumes_a_multi_generation_backlog():
    owner, client, index, checkpoint, root = await _start()
    owner_closed = False
    try:
        for number in range(5):
            await client.mutate(
                f"backlog-{number}",
                {"upsert_nodes": [_unit(f"backlog-{number}", f"v{number + 2}")]},
                kind="batch",
            )
        indexer = SearchIndexer(index, checkpoint)
        await indexer.apply_pending(client, max_generations=2)
        assert await indexer.lag(client) == 3
        await owner.close()
        owner_closed = True
        catalog = open_catalog(root / "catalog", kind="knowledge", dimension=DIMENSION)
        restarted = OvergraphOwner(root / "catalog", dimension=DIMENSION,
                                  socket_path=root / "owner.sock", catalog=catalog)
        await restarted.start()
        restarted_client = OwnerClient(restarted.socket_path, catalog_id=restarted.catalog_id)
        try:
            await SearchIndexer(index, checkpoint).apply_pending(restarted_client)
            assert await SearchIndexer(index, checkpoint).lag(restarted_client) == 0
        finally:
            await restarted.close()
    finally:
        if not owner_closed:
            await owner.close()

"""Deterministic visibility tests for the owner's native write transactions."""

from __future__ import annotations

import asyncio
import tempfile
import threading
from pathlib import Path

import pytest

from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.labels import FACT, scope_label
from app.services.overgraph.owner import OvergraphOwner, OwnerClient
from app.services.overgraph.owner_client import OwnerUnavailable

DIMENSION = 4
SCOPE = "customer:1"


def _node(key: str, *, vector: list[float] | None = None) -> dict:
    row = {
        "labels": [FACT, scope_label(SCOPE)],
        "key": key,
        "props": {"scope_key": SCOPE, "status": "active", "fact_text": key},
    }
    if vector is not None:
        row["dense_vector"] = vector
    return row


def _keys(rows: list[dict]) -> set[str]:
    return {str(row["key"]) for row in rows}


async def _start(lock_mode: str = "global"):
    root = Path(tempfile.mkdtemp(prefix="owner-txn-"))
    owner = OvergraphOwner(root / "catalog", dimension=DIMENSION, socket_path=root / "owner.sock")
    owner.lock_mode = lock_mode
    await owner.start()
    return owner, OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)


@pytest.mark.parametrize("lock_mode", ["global", "read_write"])
async def test_reader_sees_old_or_fully_committed_batch_never_partial(lock_mode):
    owner, client = await _start(lock_mode)
    try:
        await client.mutate("seed-old", {"upsert_nodes": [
            _node("old", vector=[0.0, 1.0, 0.0, 0.0]), _node("old-2"),
        ]}, kind="batch")
        seeded = await client.query_nodes(FACT, limit=100)
        old_id = next(
            row["id"] for row in seeded["nodes"] if row["key"] == "old"
        )
        await client.mutate("seed-old-edge", {"upsert_edges": [{
            "from": {"label": FACT, "key": "old"},
            "to": {"label": FACT, "key": "old-2"},
            "label": "SUBJECT",
        }]}, kind="batch")
        entered = threading.Event()
        release = threading.Event()
        owner._txn_barrier = lambda _stage: (entered.set(), release.wait(timeout=5))

        mutation = asyncio.create_task(client.mutate(
            "txn-commit",
            {
                "upsert_nodes": [
                    _node("new-a", vector=[1.0, 0.0, 0.0, 0.0]), _node("new-b"),
                ],
                "upsert_edges": [{
                    "from": {"label": FACT, "key": "new-a"},
                    "to": {"label": FACT, "key": "new-b"},
                    "label": "SUBJECT",
                }],
            },
            kind="batch",
        ))
        assert await asyncio.to_thread(entered.wait, 5)
        during = await client.query_nodes(FACT, limit=100)
        assert _keys(during["nodes"]) == {"old", "old-2"}
        assert await client.count_nodes(FACT) == 2
        hits = await client.hybrid_search(
            customer_id=1, dense_query=[1.0, 0.0, 0.0, 0.0], limit=10,
        )
        assert {hit["key"] for hit in hits} == {"old"}
        detail = await client.node(old_id)
        assert detail is not None
        assert {edge["key"] for edge in detail["edges"]} == {"old-2"}

        release.set()
        result = await asyncio.wait_for(mutation, timeout=5)
        assert result["ok"] is True
        after = await client.query_nodes(FACT, limit=100)
        assert _keys(after["nodes"]) == {"old", "old-2", "new-a", "new-b"}
    finally:
        owner._txn_barrier = None
        await owner.close()


async def test_failed_batch_rolls_back_without_partial_rows():
    owner, client = await _start()
    try:
        await client.mutate("seed-old", {"upsert_nodes": [_node("old")]}, kind="batch")
        entered = threading.Event()
        release = threading.Event()
        owner._txn_barrier = lambda _stage: (entered.set(), release.wait(timeout=5))

        mutation = asyncio.create_task(client.mutate(
            "txn-rollback",
            {
                "upsert_nodes": [_node("rollback-a")],
                "upsert_edges": [{
                    "from": {"label": FACT, "key": "rollback-a"},
                    "to": {"label": FACT, "key": "missing"},
                    "label": "SUBJECT",
                }],
            },
            kind="batch",
        ))
        assert await asyncio.to_thread(entered.wait, 5)
        release.set()
        result = await asyncio.wait_for(mutation, timeout=5)
        assert result.get("ok") is False
        assert "edge endpoint missing" in str(result.get("error"))
        after = await client.query_nodes(FACT, limit=100)
        assert _keys(after["nodes"]) == {"old"}
        retry = await client.mutate(
            "txn-after-rollback", {"upsert_nodes": [_node("after-rollback")]},
            kind="batch",
        )
        assert retry["ok"] is True
    finally:
        owner._txn_barrier = None
        await owner.close()


async def test_conditional_conflict_does_not_change_visible_state():
    owner, client = await _start()
    try:
        await client.mutate("seed-old", {"upsert_nodes": [_node("old")]}, kind="batch")
        result = await client.mutate(
            "conditional-conflict",
            {
                "read": {"label": FACT, "key": "old"},
                "expected": {"status": "wrong"},
                "upsert_nodes": [_node("should-not-appear")],
            },
            kind="conditional",
        )
        assert result.get("ok") is False
        assert result.get("error") == "precondition_failed"
        after = await client.query_nodes(FACT, limit=100)
        assert _keys(after["nodes"]) == {"old"}
    finally:
        await owner.close()


async def test_shutdown_waits_for_open_transaction_and_never_exposes_partial_state():
    owner, client = await _start()
    entered = threading.Event()
    release = threading.Event()
    owner._txn_barrier = lambda _stage: (entered.set(), release.wait(timeout=5))
    mutation = asyncio.create_task(client.mutate(
        "txn-shutdown",
        {"upsert_nodes": [_node("shutdown-a"), _node("shutdown-b")]},
        kind="batch",
    ))
    assert await asyncio.to_thread(entered.wait, 5)
    close_task = asyncio.create_task(owner.close())
    await asyncio.sleep(0.1)
    assert not close_task.done()
    release.set()
    await asyncio.wait_for(close_task, timeout=5)
    try:
        await asyncio.wait_for(mutation, timeout=5)
    except (OwnerUnavailable, OSError, RuntimeError, asyncio.CancelledError):
        pass
    raw = open_catalog(Path(owner._catalog_path), kind="knowledge", dimension=DIMENSION)
    try:
        rows, _ = raw.query_nodes(
            label_filter={"labels": [FACT], "mode": "all"}, limit=100,
        )
        keys = _keys([{"key": row.key} for row in rows])
        assert keys == set() or keys == {"shutdown-a", "shutdown-b"}
    finally:
        raw.close()


async def test_native_commit_conflict_retries_instead_of_masking_with_closed_txn():
    owner, client = await _start()
    try:
        entered = threading.Event()
        release = threading.Event()
        owner._txn_barrier = lambda _stage: (entered.set(), release.wait(timeout=5))
        mutation = asyncio.create_task(client.mutate(
            "txn-conflict",
            {"upsert_nodes": [_node("conflict-a")]},
            kind="batch",
        ))
        assert await asyncio.to_thread(entered.wait, 5)

        external = owner.catalog.begin_write_txn()
        external.upsert_node(
            [FACT, scope_label(SCOPE)], "conflict-a",
            props={"scope_key": SCOPE, "status": "external", "fact_text": "external"},
        )
        external.commit()
        release.set()

        result = await asyncio.wait_for(mutation, timeout=5)
        assert result.get("ok") is True, result
        after = await client.query_nodes(FACT, limit=100)
        row = next(row for row in after["nodes"] if row["key"] == "conflict-a")
        assert row["props"]["status"] == "active"
    finally:
        owner._txn_barrier = None
        await owner.close()

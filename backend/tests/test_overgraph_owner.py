from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from app.services.overgraph.owner import OwnerAlreadyActive, OvergraphOwner, OwnerClient


@pytest.fixture
async def owner():
    root = Path(tempfile.mkdtemp(prefix="ogo-"))
    socket_path = root / "owner.sock"
    instance = OvergraphOwner(root / "catalog", dimension=4, socket_path=socket_path)
    await instance.start()
    try:
        yield instance, OwnerClient(socket_path)
    finally:
        await instance.close()


def _node(key: str) -> dict:
    return {"labels": ["Probe", "owner-test"], "key": key, "props": {"key": key}}


async def test_concurrent_clients_both_commit(owner):
    instance, client = owner

    async def submit(index: int) -> dict:
        return await client.mutate(f"m-{index}", {"upsert_nodes": [_node(f"n-{index}")]})

    responses = await asyncio.gather(*(submit(index) for index in range(8)))
    assert all(item["ok"] for item in responses)
    for index in range(8):
        assert instance.catalog.get_by_key("Probe", f"n-{index}") is not None


async def test_duplicate_mutation_id_is_not_reapplied(owner):
    instance, client = owner
    first = {"upsert_nodes": [_node("first")]}
    assert (await client.mutate("same-id", first))["duplicate"] is False
    assert (await client.mutate("same-id", first))["duplicate"] is True
    conflict = await client.mutate("same-id", {"upsert_nodes": [_node("second")]})
    assert conflict == {"ok": False, "error": "idempotency_conflict", "mutation_id": "same-id"}
    assert instance.catalog.get_by_key("Probe", "first") is not None
    assert instance.catalog.get_by_key("Probe", "second") is None


async def test_second_owner_refuses_same_catalog(tmp_path: Path):
    socket_path = tmp_path / "owner.sock"
    first = OvergraphOwner(tmp_path / "catalog", dimension=4, socket_path=socket_path)
    try:
        with pytest.raises(OwnerAlreadyActive):
            OvergraphOwner(tmp_path / "catalog", dimension=4, socket_path=socket_path)
    finally:
        await first.close()


async def test_stale_socket_is_replaced_only_after_lock(owner):
    instance, _client = owner
    assert instance.socket_path.exists()
    # A stale socket path does not grant ownership; a second owner still fails.
    with pytest.raises(OwnerAlreadyActive):
        OvergraphOwner(instance._catalog_path, dimension=4, socket_path=instance.socket_path)


async def test_receipt_survives_owner_restart():
    root = Path(tempfile.mkdtemp(prefix="ogo-"))
    socket_path = root / "owner.sock"
    first = OvergraphOwner(root / "catalog", dimension=4, socket_path=socket_path)
    await first.start()
    client = OwnerClient(socket_path)
    persisted = {"upsert_nodes": [_node("before-restart")]}
    await client.mutate("persisted", persisted)
    await first.close()

    second = OvergraphOwner(root / "catalog", dimension=4, socket_path=socket_path)
    await second.start()
    try:
        duplicate = await client.mutate("persisted", persisted)
        assert duplicate["duplicate"] is True
        conflict = await client.mutate("persisted", {"upsert_nodes": [_node("after-restart")]})
        assert conflict["error"] == "idempotency_conflict"
        assert second.catalog.get_by_key("Probe", "after-restart") is None
    finally:
        await second.close()


async def test_conditional_write_txn_increments(owner):
    instance, client = owner
    # Seed with a normal patch, then use conditional read-modify-write.
    seeded = await client.mutate("gen-seed", {"upsert_nodes": [{"labels": ["Generation"], "key": "scope", "props": {"generation": 0}}]})
    assert seeded["ok"] is True
    mutation = {"read": {"label": "Generation", "key": "scope"}, "increments": [{"prop": "generation", "by": 1}], "result_props": ["generation"]}
    responses = await asyncio.gather(
        *(client.mutate(f"gen-{index}", mutation, kind="conditional") for index in range(1, 4))
    )
    assert all(item["ok"] for item in responses)
    receipt = instance.catalog.get_by_key("Generation", "scope")
    assert receipt is not None
    assert int(receipt.props["generation"]) == 3


def _batch_patch(nodes, *, expected=None):
    payload = {
        "generation": {"label": "Generation", "key": "scope", "prop": "generation"},
        "upsert_nodes": nodes,
    }
    if expected is not None:
        payload["expected"] = expected
    return payload


async def test_batch_noop_does_not_bump_generation(owner):
    instance, client = owner
    seeded = await client.mutate("seed-gen", {"upsert_nodes": [{"labels": ["Generation"], "key": "scope", "props": {"generation": 0}}]})
    assert seeded["ok"] is True
    nodes = [
        {"labels": ["TextUnit", "scope"], "key": "u1", "props": {"text": "a", "content_hash": "h1"}},
        {"labels": ["TextUnit", "scope"], "key": "u2", "props": {"text": "b", "content_hash": "h2"}},
    ]
    first = await client.mutate("batch-1", _batch_patch(nodes), kind="batch")
    assert first["changed"] == 2
    assert first["previous_generation"] == 0
    assert first["generation"] == 1
    same = await client.mutate("batch-2", _batch_patch(nodes), kind="batch")
    assert same["changed"] == 0
    assert same["generation"] == 1
    assert int(instance.catalog.get_by_key("Generation", "scope").props["generation"]) == 1


async def test_batch_precondition_is_not_retried(owner):
    instance, client = owner
    await client.mutate("seed-gen", {"upsert_nodes": [{"labels": ["Generation"], "key": "scope", "props": {"generation": 2}}]})
    response = await client.mutate(
        "batch-precondition",
        _batch_patch([{"labels": ["TextUnit"], "key": "u3", "props": {"text": "c"}}], expected={"generation": 1}),
        kind="batch",
    )
    assert response["error"] == "precondition_failed"
    assert instance.catalog.get_by_key("TextUnit", "u3") is None


async def test_committed_mutation_without_response_is_a_receipt(owner):
    instance, client = owner
    request = __import__("app.services.overgraph.owner", fromlist=["MutationRequest"]).MutationRequest(
        mutation_id="crash-after-commit",
        patch={"upsert_nodes": [_node("committed-before-crash")]},
    )
    result = instance._apply(request)
    assert result["ok"] is True
    # Simulate the client retrying after a crash/restart: same id and payload.
    retry = await client.mutate("crash-after-commit", request.patch)
    assert retry["duplicate"] is True
    assert instance.catalog.get_by_key("Probe", "committed-before-crash") is not None


async def test_batch_1000_text_units_is_one_generation(owner):
    instance, client = owner
    await client.mutate("seed-gen", {"upsert_nodes": [{"labels": ["Generation"], "key": "scope", "props": {"generation": 0}}]})
    nodes = [
        {"labels": ["TextUnit", "scope"], "key": f"bulk-{index}", "props": {"text": str(index), "content_hash": str(index)}}
        for index in range(1000)
    ]
    result = await client.mutate("bulk-1000", _batch_patch(nodes), kind="batch")
    assert result["changed"] == 1000
    assert result["generation"] == 1
    assert int(instance.catalog.get_by_key("Generation", "scope").props["generation"]) == 1


async def test_batch_with_dense_vectors_changes_only_one_node(owner):
    instance, client = owner
    await client.mutate("seed-gen", {"upsert_nodes": [{"labels": ["Generation"], "key": "scope", "props": {"generation": 0}}]})
    nodes = [
        {
            "labels": ["TextUnit", "scope"], "key": f"vec-{index}",
            "props": {"text": str(index), "content_hash": str(index)},
            "dense_vector": [float(index), 0.0, 0.0, 0.0],
        }
        for index in range(1000)
    ]
    first = await client.mutate("vec-batch-1", _batch_patch(nodes), kind="batch")
    assert first["changed"] == 1000
    assert first["generation"] == 1
    changed = [dict(node) for node in nodes]
    changed[500]["dense_vector"] = [999.0, 1.0, 0.0, 0.0]
    second = await client.mutate("vec-batch-2", _batch_patch(changed), kind="batch")
    assert second["changed"] == 1
    assert second["generation"] == 2

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from app.services.overgraph.owner import OvergraphOwner, OwnerClient


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
    assert (await client.mutate("same-id", {"upsert_nodes": [_node("first")]}))["duplicate"] is False
    assert (await client.mutate("same-id", {"upsert_nodes": [_node("second")]}))["duplicate"] is True
    assert instance.catalog.get_by_key("Probe", "first") is not None
    assert instance.catalog.get_by_key("Probe", "second") is None


async def test_receipt_survives_owner_restart():
    root = Path(tempfile.mkdtemp(prefix="ogo-"))
    socket_path = root / "owner.sock"
    first = OvergraphOwner(root / "catalog", dimension=4, socket_path=socket_path)
    await first.start()
    client = OwnerClient(socket_path)
    await client.mutate("persisted", {"upsert_nodes": [_node("before-restart")]})
    await first.close()

    second = OvergraphOwner(root / "catalog", dimension=4, socket_path=socket_path)
    await second.start()
    try:
        duplicate = await client.mutate("persisted", {"upsert_nodes": [_node("after-restart")]})
        assert duplicate["duplicate"] is True
        assert second.catalog.get_by_key("Probe", "after-restart") is None
    finally:
        await second.close()

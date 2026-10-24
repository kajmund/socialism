from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.services.overgraph.owner import OwnerUnavailable, OvergraphOwner
from app.services.overgraph.owner_runtime import OwnerRuntime


@pytest.fixture
async def owner():
    root = Path(tempfile.mkdtemp(prefix="ogo-"))
    instance = OvergraphOwner(root / "catalog", dimension=4, socket_path=root / "owner.sock")
    await instance.start()
    try:
        yield instance
    finally:
        await instance.close()


async def test_runtime_reports_owner_ready_but_write_paths_not_migrated(owner):
    runtime = OwnerRuntime()
    await runtime.connect(str(owner.socket_path), catalog_id=owner.catalog_id)
    assert runtime.status["status"] == "ready"
    assert runtime.status["write_paths_ready"] is False
    assert runtime.require_client() is runtime.client


async def test_runtime_fails_closed_when_owner_missing(tmp_path: Path):
    runtime = OwnerRuntime()
    await runtime.connect(str(tmp_path / "missing.sock"))
    assert runtime.status["status"] == "unavailable"
    with pytest.raises(OwnerUnavailable):
        runtime.require_client()


async def test_catalog_identity_survives_restart():
    root = Path(tempfile.mkdtemp(prefix="ogo-"))
    first = OvergraphOwner(root / "catalog", dimension=4, socket_path=root / "a.sock")
    identity = first.catalog_id
    await first.close()
    second = OvergraphOwner(root / "catalog", dimension=4, socket_path=root / "b.sock")
    try:
        assert second.catalog_id == identity
    finally:
        await second.close()


async def test_owner_read_path(owner):
    runtime = OwnerRuntime()
    await runtime.connect(str(owner.socket_path), catalog_id=owner.catalog_id)
    client = runtime.require_client()
    await client.mutate("read-test", {"upsert_nodes": [{"labels": ["Probe"], "key": "read-key", "props": {"value": "x"}}]})
    values = await client.read([{"label": "Probe", "key": "read-key"}])
    assert values["values"]["Probe:read-key"] == {"value": "x"}

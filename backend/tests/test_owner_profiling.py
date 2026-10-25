"""Profiling flags are opt-in and do not change the default owner path."""

from __future__ import annotations

import asyncio
import tempfile
import time

import pytest
from pathlib import Path

from app.services.overgraph.owner import OvergraphOwner, OwnerClient
from app.services.overgraph.owner_client import OwnerUnavailable


async def test_event_loop_lag_monitor_and_bounded_read_workers():
    root = Path(tempfile.mkdtemp(prefix="ogo-profile-"))
    owner = OvergraphOwner(root / "catalog", dimension=4, socket_path=root / "owner.sock")
    owner.profile_lag = True
    owner.read_workers = 2
    await owner.start()
    client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    try:
        await asyncio.sleep(0.05)
        health = await client.health()
        assert health["metrics"]["event_loop_lag_seconds"]
        page = await client.query_nodes("TextUnit", limit=1)
        assert page["nodes"] == []
        assert page["next_cursor"] is None
    finally:
        await owner.close()


async def test_close_waits_for_inflight_reads_before_closing_catalog(monkeypatch):
    import app.services.overgraph.owner_execution as owner_module

    root = Path(tempfile.mkdtemp(prefix="ogo-profile-close-"))
    owner = OvergraphOwner(root / "catalog", dimension=4, socket_path=root / "owner.sock")
    owner.read_workers = 2
    await owner.start()
    client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    real = owner_module.handle_read

    def slow_read(payload, catalog, catalog_id):
        time.sleep(0.2)
        return real(payload, catalog, catalog_id)

    monkeypatch.setattr(owner_module, "handle_read", slow_read)
    read = asyncio.create_task(client.query_nodes("TextUnit", limit=1))
    await asyncio.sleep(0.05)
    await asyncio.wait_for(owner.close(), timeout=5)
    try:
        await asyncio.wait_for(read, timeout=2)
    except (OwnerUnavailable, OSError, RuntimeError, asyncio.CancelledError):
        pass
    with pytest.raises(OwnerUnavailable):
        await client.query_nodes("TextUnit", limit=1)


async def test_read_submission_failure_does_not_leak_inflight(monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="ogo-inflight-"))
    owner = OvergraphOwner(root / "catalog", dimension=4, socket_path=root / "owner.sock")
    owner.read_workers = 2
    await owner.start()
    try:
        reads = owner._reads

        class FailingExecutor:
            def submit(self, *_args, **_kwargs):
                raise RuntimeError("cannot schedule new futures")

            def shutdown(self, **_kwargs):
                return None

        reads.executor = FailingExecutor()
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(
                reads.read({"type": "query_nodes", "label": "TextUnit", "limit": 1},
                           owner.catalog_id),
                timeout=2,
            )
        assert reads._inflight == 0
        await asyncio.wait_for(owner.close(), timeout=2)
    finally:
        if owner._reads is not None:
            owner._reads.executor = None

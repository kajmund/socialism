"""Profiling flags are opt-in and do not change the default owner path."""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from app.services.overgraph.owner import OvergraphOwner, OwnerClient


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
    except (OSError, RuntimeError, asyncio.CancelledError):
        pass

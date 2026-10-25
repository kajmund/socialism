"""Profiling flags are opt-in and do not change the default owner path."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from app.services.overgraph.owner import OvergraphOwner, OwnerClient


async def test_event_loop_lag_monitor_and_read_offload_are_opt_in():
    root = Path(tempfile.mkdtemp(prefix="ogo-profile-"))
    owner = OvergraphOwner(root / "catalog", dimension=4, socket_path=root / "owner.sock")
    owner.profile_lag = True
    owner.read_offload = True
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

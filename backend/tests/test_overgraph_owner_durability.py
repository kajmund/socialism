"""Durability and exclusivity with a real owner OS process.

These tests start the owner through its CLI (separate process), acknowledge a
mutation, SIGKILL the process before its group-commit timer could help, restart
it and read the data back. That proves process-crash recovery after an ack, not
power-loss durability (which additionally depends on fsync/media semantics).
"""

from __future__ import annotations

import asyncio
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.owner import OwnerClient, OvergraphOwner, OwnerUnavailable

BACKEND = Path(__file__).resolve().parents[1]


def _start_owner(root: Path, *, sync: bool = True) -> subprocess.Popen[str]:
    argv = [
        sys.executable, "-m", "app.services.overgraph.owner",
        str(root / "catalog"), "--socket", str(root / "owner.sock"),
        "--dimension", "4",
    ]
    if not sync:
        argv.append("--no-sync")
    process = subprocess.Popen(
        argv, cwd=BACKEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        text=True,
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            asyncio.run(OwnerClient(root / "owner.sock").health())
            return process
        except (OwnerUnavailable, OSError, ConnectionError):
            time.sleep(0.05)
    process.kill()
    raise TimeoutError("owner did not become ready")


def _stop(process: subprocess.Popen[str], *, sig: int = signal.SIGTERM) -> None:
    if process.poll() is None:
        process.send_signal(sig)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _mutate(socket_path: Path, key: str) -> dict:
    return asyncio.run(OwnerClient(socket_path).mutate(
        f"durable-{key}",
        {"upsert_nodes": [{
            "labels": ["DurabilityProbe", "owner-test"],
            "key": key,
            "props": {"value": key},
        }]},
        kind="batch",
    ))


def test_acked_mutation_survives_owner_sigkill_and_replays_as_duplicate():
    root = Path(tempfile.mkdtemp(prefix="ogo-kill-"))
    owner = _start_owner(root)
    try:
        health = asyncio.run(OwnerClient(root / "owner.sock").health())
        assert health["sync_on_commit"] is True
        result = _mutate(root / "owner.sock", "acked")
        assert result["ok"] is True
        health = asyncio.run(OwnerClient(root / "owner.sock").health())
        assert health["metrics"]["sync_seconds"], "durable ack must fsync before responding"
        owner.kill()  # SIGKILL: no close(), no timer
        owner.wait(timeout=10)
        owner = _start_owner(root)
        rows = asyncio.run(OwnerClient(root / "owner.sock").list_nodes("DurabilityProbe"))
        assert [row["key"] for row in rows] == ["acked"]
        replay = _mutate(root / "owner.sock", "acked")
        assert replay["duplicate"] is True
        catalog = open_catalog(root / "catalog", kind="knowledge", dimension=4)
        try:
            assert catalog.count_nodes_by_labels(["DurabilityProbe"]) == 1
        finally:
            catalog.close()
    finally:
        _stop(owner)


def test_second_owner_process_is_rejected_while_catalog_is_owned():
    root = Path(tempfile.mkdtemp(prefix="ogo-excl-"))
    owner = _start_owner(root)
    try:
        second = subprocess.run(
            [
                sys.executable, "-m", "app.services.overgraph.owner",
                str(root / "catalog"), "--socket", str(root / "second.sock"),
                "--dimension", "4",
            ],
            cwd=BACKEND, capture_output=True, text=True, timeout=20,
        )
        assert second.returncode != 0
        assert "already owned" in (second.stdout + second.stderr).lower()
    finally:
        _stop(owner)


def test_sync_failure_does_not_ack_and_duplicate_retry_syncs():
    root = Path(tempfile.mkdtemp(prefix="ogo-sync-"))
    catalog = open_catalog(root / "catalog", kind="knowledge", dimension=4)
    calls = {"count": 0}
    real_sync = catalog.sync

    def flaky_sync() -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("injected fsync failure")
        real_sync()

    catalog.sync = flaky_sync  # type: ignore[method-assign]
    owner = OvergraphOwner(
        root / "catalog", dimension=4, socket_path=root / "owner.sock",
        catalog=catalog, sync_on_commit=True,
    )

    async def run() -> None:
        await owner.start()
        try:
            client = OwnerClient(root / "owner.sock", catalog_id=owner.catalog_id)
            patch = {"upsert_nodes": [{
                "labels": ["DurabilityProbe", "owner-test"],
                "key": "retry",
                "props": {"value": 1},
            }]}
            first = await client.mutate("sync-failure-1", patch, kind="batch")
            assert first["ok"] is False
            assert "durability_sync_failed" in first["error"]
            second = await client.mutate("sync-failure-1", patch, kind="batch")
            assert second["ok"] is True and second["duplicate"] is True
            assert owner.metrics.sync_seconds, (
                "duplicate retry must fsync the earlier unsynced commit"
            )
        finally:
            await owner.close()

    try:
        asyncio.run(run())
    finally:
        catalog.close()


@pytest.mark.parametrize("sync", [True, False])
def test_owner_cli_health_reports_sync_mode(sync):
    root = Path(tempfile.mkdtemp(prefix="ogo-mode-"))
    owner = _start_owner(root, sync=sync)
    try:
        health = asyncio.run(OwnerClient(root / "owner.sock").health())
        assert health["sync_on_commit"] is sync
    finally:
        _stop(owner)

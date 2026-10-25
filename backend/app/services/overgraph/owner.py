"""Single-writer Overgraph catalog owner.

Only the owner process opens the catalog for writes. Clients submit bounded,
idempotent mutation batches over a Unix socket. The idempotency receipt and the
data mutation are written in one Catalog.graph_patch, so a retry after a lost
response cannot apply the mutation twice.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import time
import os
from pathlib import Path
from typing import Any

from overgraph import OverGraphError

from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.owner_reads import handle_read
from app.services.overgraph.owner_client import (
    IdempotencyConflict,
    MutationRequest,
    OwnerAlreadyActive,
    OwnerClient,
    METRIC_SAMPLES,
    OwnerMetrics,
    OwnerProtocolError,
    OwnerQueueFull,
    OwnerUnavailable,
    _record_sample,
    load_catalog_id,
    payload_hash as compute_payload_hash,
)

__all__ = [
    "IdempotencyConflict",
    "MutationRequest",
    "OvergraphOwner",
    "OwnerAlreadyActive",
    "OwnerClient",
    "OwnerMetrics",
    "OwnerProtocolError",
    "OwnerQueueFull",
    "OwnerUnavailable",
]

RECEIPT_LABEL = "MutationReceipt"


class OvergraphOwner:
    def __init__(
        self,
        path: Path,
        *,
        dimension: int,
        socket_path: Path,
        max_queue: int = 256,
        catalog_id: str | None = None,
        catalog: Any | None = None,
        sync_on_commit: bool = True,
    ) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self.catalog_id = catalog_id or load_catalog_id(path)
        self._lock_fd = os.open(path / ".owner.lock", os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self._lock_fd)
            raise OwnerAlreadyActive(f"catalog is already owned: {path}") from exc
        self._catalog_path = path
        self._owns_catalog = catalog is None
        self.catalog = open_catalog(path, kind="knowledge", dimension=dimension) if catalog is None else catalog
        self.socket_path = socket_path
        self.max_queue = max_queue
        self.sync_on_commit = sync_on_commit
        self.profile_lag = False
        self.read_offload = False
        self.queue: asyncio.Queue[tuple[MutationRequest, asyncio.Future[dict[str, Any]]]] = asyncio.Queue(
            maxsize=max_queue
        )
        self.metrics = OwnerMetrics()
        self.read_revision = 0
        self._worker: asyncio.Task[None] | None = None
        self._lag_monitor: asyncio.Task[None] | None = None
        self._server: asyncio.AbstractServer | None = None
        self._closed = False

    async def start(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self.socket_path.unlink(missing_ok=True)
        self._worker = asyncio.create_task(self._run_worker())
        if self.profile_lag:
            self._lag_monitor = asyncio.create_task(self._measure_event_loop_lag())
        self._server = await asyncio.start_unix_server(self._handle, path=str(self.socket_path), limit=16 * 1024 * 1024)

    async def close(self) -> None:
        self._closed = True
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        if self._worker is not None:
            # Let in-flight handlers observe _closed and reject new submits,
            # then fail anything still queued so queue.join() cannot hang. The
            # worker itself keeps draining until cancelled.
            await asyncio.sleep(0)
            while not self.queue.empty():
                _request, future = self.queue.get_nowait()
                if not future.done():
                    future.set_exception(OwnerUnavailable("owner is shutting down"))
                self.queue.task_done()
            await self.queue.join()
            await asyncio.sleep(0)
            while not self.queue.empty():
                _request, future = self.queue.get_nowait()
                if not future.done():
                    future.set_exception(OwnerUnavailable("owner is shutting down"))
                self.queue.task_done()
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
        if self._lag_monitor is not None:
            self._lag_monitor.cancel()
            try:
                await self._lag_monitor
            except asyncio.CancelledError:
                pass
        if self._owns_catalog:
            self.catalog.close()
        self.socket_path.unlink(missing_ok=True)
        fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        os.close(self._lock_fd)

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> None:
        try:
            line = await reader.readline()
            if not line:
                return
            payload = json.loads(line)
            started = time.perf_counter()
            if self.read_offload:
                read_response = await asyncio.to_thread(
                    handle_read, payload, self.catalog, self.catalog_id,
                )
            else:
                read_response = handle_read(payload, self.catalog, self.catalog_id)
            if read_response is not None:
                read_response.setdefault("read_revision", self.read_revision)
                encoded = (json.dumps(read_response) + "\n").encode()
                self.metrics.read_ops += 1
                self.metrics.read_objects += len(read_response.get("nodes") or read_response.get("values") or {})
                self.metrics.read_bytes += len(encoded)
                _record_sample(self.metrics.read_seconds, started)
                writer.write(encoded)
                await writer.drain()
                return
            if payload.get("type") == "health":
                writer.write((json.dumps({
                    "ok": True,
                    "catalog_id": self.catalog_id,
                    "sync_on_commit": self.sync_on_commit,
                    "read_revision": self.read_revision,
                    "metrics": self.metrics.__dict__,
                }) + "\n").encode())
                await writer.drain()
                return
            if payload.get("catalog_id") != self.catalog_id:
                writer.write((json.dumps({"ok": False, "error": "catalog_mismatch"}) + "\n").encode())
                await writer.drain()
                return
            if self._closed:
                writer.write((json.dumps({"ok": False, "error": "owner_closed"}) + "\n").encode())
                await writer.drain()
                return
            request = MutationRequest(
                mutation_id=str(payload["mutation_id"]),
                patch=dict(payload.get("patch") or {}),
                kind=str(payload.get("kind") or "patch"),
            )
            future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
            try:
                self.queue.put_nowait((request, future))
            except asyncio.QueueFull:
                self.metrics.rejected += 1
                writer.write((json.dumps({"ok": False, "error": "queue_full"}) + "\n").encode())
                await writer.drain()
                return
            self.metrics.queue_high_water = max(self.metrics.queue_high_water, self.queue.qsize())
            try:
                response = await future
            except Exception as exc:  # noqa: BLE001 - surfaced to the client
                response = {"ok": False, "error": str(exc)}
            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _measure_event_loop_lag(self) -> None:
        interval = 0.005
        next_at = time.perf_counter() + interval
        while True:
            await asyncio.sleep(interval)
            now = time.perf_counter()
            self.metrics.event_loop_lag_seconds.append(round(max(0.0, now - next_at), 6))
            del self.metrics.event_loop_lag_seconds[:-METRIC_SAMPLES]
            next_at = now + interval

    async def _run_worker(self) -> None:
        while True:
            request, future = await self.queue.get()
            _record_sample(self.metrics.queue_wait_seconds, request.enqueued_at)
            try:
                if future.cancelled():
                    continue
                result = await asyncio.to_thread(self._apply, request)
                if result.get("ok") and self.sync_on_commit:
                    # An ack must mean durable: group_commit only fsyncs on its
                    # ~50 ms timer, so a small commit is still in a userspace
                    # buffer when the mutation returns. Duplicates sync too: the
                    # original sync may have failed after its commit.
                    try:
                        started = time.perf_counter()
                        await asyncio.to_thread(self.catalog.sync)
                        _record_sample(self.metrics.sync_seconds, started)
                    except (OverGraphError, OSError) as exc:  # persisted, unacked
                        self.metrics.rejected += 1
                        result = {
                            "ok": False,
                            "error": f"durability_sync_failed: {type(exc).__name__}",
                            "mutation_id": request.mutation_id,
                        }
                if result.get("ok") and not result.get("duplicate"):
                    self.read_revision += 1
                future.set_result(result)
            except Exception as exc:  # noqa: BLE001 - surfaced to client
                if not future.done():
                    future.set_exception(exc)
            finally:
                self.queue.task_done()

    def _apply(self, request: MutationRequest) -> dict[str, Any]:
        payload_hash = compute_payload_hash(request)
        receipt = self.catalog.get_by_key(RECEIPT_LABEL, request.mutation_id)
        if receipt is not None:
            previous = str(receipt.props.get("payload_hash", ""))
            if previous != payload_hash:
                self.metrics.rejected += 1
                return {"ok": False, "error": "idempotency_conflict", "mutation_id": request.mutation_id}
            self.metrics.duplicates += 1
            return {"ok": True, "duplicate": True, "mutation_id": request.mutation_id}
        if request.kind == "conditional":
            return self._apply_conditional(request, payload_hash)
        if request.kind == "batch":
            return self._apply_batch(request, payload_hash)
        if request.kind == "embedding":
            return self._apply_embeddings(request, payload_hash)
        patch = dict(request.patch)
        nodes = list(patch.get("upsert_nodes", ()))
        nodes.append(self._receipt_node(request.mutation_id, payload_hash))
        patch["upsert_nodes"] = nodes
        started = time.perf_counter()
        self.catalog.graph_patch(**patch)
        _record_sample(self.metrics.commit_seconds, started)
        self.metrics.applied += 1
        return {"ok": True, "duplicate": False, "mutation_id": request.mutation_id}

    @staticmethod
    def _receipt_node(mutation_id: str, payload_hash: str) -> dict[str, Any]:
        return {
            "labels": [RECEIPT_LABEL, "overgraph-owner"],
            "key": mutation_id,
            "props": {"mutation_id": mutation_id, "payload_hash": payload_hash},
        }

    def _apply_conditional(self, request: MutationRequest, payload_hash: str) -> dict[str, Any]:
        read = dict(request.patch["read"])
        expected = dict(request.patch.get("expected") or {})
        increments = list(request.patch.get("increments") or [])
        nodes = list(request.patch.get("upsert_nodes", ()))
        for attempt in range(3):
            txn = self.catalog.begin_write_txn()
            committed = False
            try:
                current = txn.get_node_by_key(str(read["label"]), str(read["key"]))
                if current is None:
                    return {"ok": False, "error": "read_not_found", "mutation_id": request.mutation_id}
                props = dict(current.get("props") or {})
                if expected and any(props.get(name) != value for name, value in expected.items()):
                    return {"ok": False, "error": "precondition_failed", "mutation_id": request.mutation_id}
                response_props = {name: props.get(name) for name in request.patch.get("result_props", ())}
                for increment in increments:
                    name = str(increment["prop"])
                    props[name] = int(props.get(name) or 0) + int(increment.get("by", 1))
                for node in nodes:
                    txn.upsert_node(
                        list(node["labels"]), str(node["key"]),
                        props=dict(node.get("props") or {}),
                        dense_vector=node.get("dense_vector"),
                    )
                if increments:
                    txn.upsert_node(
                        list(read.get("labels") or [read["label"]]),
                        str(read["key"]),
                        props=props,
                    )
                txn.upsert_node(
                    [RECEIPT_LABEL, "overgraph-owner"], request.mutation_id,
                    props={"mutation_id": request.mutation_id, "payload_hash": payload_hash},
                )
                started = time.perf_counter()
                txn.commit()
                _record_sample(self.metrics.commit_seconds, started)
                committed = True
                self.metrics.applied += 1
                return {
                    "ok": True, "duplicate": False, "mutation_id": request.mutation_id,
                    "props": response_props,
                }
            except OverGraphError as exc:
                if "conflict" not in str(exc).lower():
                    raise
                self.metrics.conflicts += 1
                if attempt == 2:
                    raise
            finally:
                if not committed:
                    txn.rollback()
        raise RuntimeError("unreachable")

    @staticmethod
    def _same_node(current: Any, node: dict[str, Any]) -> bool:
        if current is None:
            return False
        if dict(current.get("props") or {}) != dict(node.get("props") or {}):
            return False
        expected_vector = node.get("dense_vector")
        if expected_vector is not None and list(current.get("dense_vector") or []) != list(expected_vector):
            return False
        return True

    def _apply_batch(  # noqa: C901, PLR0912, PLR0915
        self, request: MutationRequest, payload_hash: str,
    ) -> dict[str, Any]:
        """Batch upsert with no-op detection and optional one generation bump."""
        generation = dict(request.patch.get("generation") or {})
        expected = dict(request.patch.get("expected") or {})
        nodes = list(request.patch.get("upsert_nodes", ()))
        edges = list(request.patch.get("upsert_edges", ()))
        deletes = list(request.patch.get("delete_nodes", ()))
        expected_nodes = list(request.patch.get("expected_nodes", ()))
        expected_absent = list(request.patch.get("expected_absent", ()))
        for attempt in range(3):
            txn = self.catalog.begin_write_txn()
            committed = False
            try:
                for absent in expected_absent:
                    if txn.get_node_by_key(str(absent["label"]), str(absent["key"])) is not None:
                        return {"ok": False, "error": "precondition_failed", "mutation_id": request.mutation_id}
                for expected_node in expected_nodes:
                    current = txn.get_node_by_key(
                        str(expected_node["label"]), str(expected_node["key"]),
                    )
                    if current is None or any(
                        dict(current.get("props") or {}).get(name) != value
                        for name, value in dict(expected_node.get("props") or {}).items()
                    ):
                        return {"ok": False, "error": "precondition_failed", "mutation_id": request.mutation_id}
                previous_generation = None
                generation_node = None
                generation_props: dict[str, Any] = {}
                if generation:
                    generation_node = txn.get_node_by_key(str(generation["label"]), str(generation["key"]))
                    if generation_node is None:
                        return {"ok": False, "error": "generation_not_found", "mutation_id": request.mutation_id}
                    generation_props = dict(generation_node.get("props") or {})
                    if expected and any(generation_props.get(name) != value for name, value in expected.items()):
                        return {"ok": False, "error": "precondition_failed", "mutation_id": request.mutation_id}
                    previous_generation = generation_props.get(str(generation["prop"]))
                changed = 0
                for node in nodes:
                    current = txn.get_node_by_key(str(node["labels"][0]), str(node["key"]))
                    if self._same_node(current, node):
                        continue
                    txn.upsert_node(
                        list(node["labels"]), str(node["key"]),
                        props=dict(node.get("props") or {}),
                        dense_vector=node.get("dense_vector"),
                    )
                    changed += 1
                for item in deletes:
                    current = txn.get_node_by_key(str(item["label"]), str(item["key"]))
                    if current is not None:
                        txn.delete_node({"id": current["id"]})
                        changed += 1
                for edge in edges:
                    from_row = txn.get_node_by_key(str(edge["from"]["label"]), str(edge["from"]["key"]))
                    to_row = txn.get_node_by_key(str(edge["to"]["label"]), str(edge["to"]["key"]))
                    if from_row is None or to_row is None:
                        raise OwnerProtocolError("edge endpoint missing")
                    txn.upsert_edge(
                        {"labels": [from_row["labels"][0]], "key": from_row["key"]},
                        {"labels": [to_row["labels"][0]], "key": to_row["key"]},
                        str(edge["label"]),
                        props=dict(edge.get("props") or {}),
                        valid_from=edge.get("valid_from"),
                        valid_to=edge.get("valid_to"),
                    )
                if changed and generation:
                    prop = str(generation["prop"])
                    generation_props[prop] = int(generation_props.get(prop) or 0) + 1
                    txn.upsert_node(
                        list(generation.get("labels") or [generation["label"]]),
                        str(generation["key"]),
                        props=generation_props,
                    )
                txn.upsert_node(
                    [RECEIPT_LABEL, "overgraph-owner"], request.mutation_id,
                    props={"mutation_id": request.mutation_id, "payload_hash": payload_hash},
                )
                started = time.perf_counter()
                txn.commit()
                _record_sample(self.metrics.commit_seconds, started)
                committed = True
                self.metrics.applied += 1
                return {
                    "ok": True, "duplicate": False, "mutation_id": request.mutation_id,
                    "changed": changed,
                    "previous_generation": previous_generation,
                    "generation": generation_props.get(str(generation["prop"])) if generation else None,
                }
            except OverGraphError as exc:
                if "conflict" not in str(exc).lower():
                    raise
                self.metrics.conflicts += 1
                if attempt == 2:
                    raise
            finally:
                if not committed:
                    txn.rollback()
        raise RuntimeError("unreachable")

    def _apply_embeddings(self, request: MutationRequest, payload_hash: str) -> dict[str, Any]:
        """Update dense vectors only when the TextUnit content is unchanged."""
        updates = list(request.patch.get("embedding_updates", ()))
        for attempt in range(3):
            txn = self.catalog.begin_write_txn()
            committed = False
            try:
                for update in updates:
                    row = txn.get_node_by_key(str(update["label"]), str(update["key"]))
                    if row is None:
                        return {"ok": False, "error": "text_unit_not_found", "mutation_id": request.mutation_id}
                    if str(row["props"].get("content_hash", "")) != str(update["content_hash"]):
                        return {"ok": False, "error": "stale_embedding", "mutation_id": request.mutation_id}
                    txn.upsert_node(
                        list(row["labels"]), str(update["key"]),
                        props=dict(row["props"]),
                        dense_vector=list(update["vector"]),
                    )
                txn.upsert_node(
                    [RECEIPT_LABEL, "overgraph-owner"], request.mutation_id,
                    props={"mutation_id": request.mutation_id, "payload_hash": payload_hash},
                )
                started = time.perf_counter()
                txn.commit()
                _record_sample(self.metrics.commit_seconds, started)
                committed = True
                self.metrics.applied += 1
                return {"ok": True, "duplicate": False, "mutation_id": request.mutation_id}
            except OverGraphError as exc:
                if "conflict" not in str(exc).lower():
                    raise
                self.metrics.conflicts += 1
                if attempt == 2:
                    raise
            finally:
                if not committed:
                    txn.rollback()
        raise RuntimeError("unreachable")


if __name__ == "__main__":
    from app.services.overgraph.owner_cli import main

    raise SystemExit(main())

"""Single-writer Overgraph catalog owner.

Only the owner process opens the catalog for writes. Clients submit bounded,
idempotent mutation batches over a Unix socket. The idempotency receipt and the
data mutation are written in one Catalog.graph_patch, so a retry after a lost
response cannot apply the mutation twice.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from overgraph import OverGraphError

from app.services.overgraph.catalogs import open_catalog

RECEIPT_LABEL = "MutationReceipt"


class OwnerQueueFull(RuntimeError):
    pass


class OwnerAlreadyActive(RuntimeError):
    """Another process already owns this catalog."""


class IdempotencyConflict(RuntimeError):
    """A mutation id was reused with a different payload."""


class OwnerUnavailable(RuntimeError):
    """The owner is not reachable; retry the same mutation id."""


class OwnerProtocolError(RuntimeError):
    """The owner returned an error that must not be retried blindly."""


@dataclass
class MutationRequest:
    mutation_id: str
    patch: dict[str, Any]
    kind: str = "patch"


@dataclass
class OwnerMetrics:
    applied: int = 0
    duplicates: int = 0
    rejected: int = 0
    conflicts: int = 0
    queue_high_water: int = 0
    wait_seconds: list[float] = field(default_factory=list)


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
    ) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self.catalog_id = catalog_id or self._load_catalog_id(path)
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
        self.queue: asyncio.Queue[tuple[MutationRequest, asyncio.Future[dict[str, Any]]]] = asyncio.Queue(
            maxsize=max_queue
        )
        self.metrics = OwnerMetrics()
        self._worker: asyncio.Task[None] | None = None
        self._server: asyncio.AbstractServer | None = None
        self._closed = False

    @staticmethod
    def _load_catalog_id(path: Path) -> str:
        identity_file = path.parent / f".{path.name}.overgraph-owner-id"
        try:
            existing = identity_file.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        except FileNotFoundError:
            pass
        identity = secrets.token_hex(16)
        fd = os.open(identity_file, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            os.write(fd, identity.encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        return identity

    async def start(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self.socket_path.unlink(missing_ok=True)
        self._worker = asyncio.create_task(self._run_worker())
        self._server = await asyncio.start_unix_server(self._handle, path=str(self.socket_path), limit=16 * 1024 * 1024)

    async def close(self) -> None:
        self._closed = True
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        if self._worker is not None:
            await self.queue.join()
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
        if self._owns_catalog:
            self.catalog.close()
        self.socket_path.unlink(missing_ok=True)
        fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        os.close(self._lock_fd)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            if not line:
                return
            payload = json.loads(line)
            if payload.get("type") == "read":
                if payload.get("catalog_id") != self.catalog_id:
                    writer.write((json.dumps({"ok": False, "error": "catalog_mismatch"}) + "\n").encode())
                    await writer.drain()
                    return
                values = {}
                for item in payload.get("keys", []):
                    row = self.catalog.get_by_key(str(item["label"]), str(item["key"]))
                    values[f"{item['label']}:{item['key']}"] = None if row is None else dict(row.props)
                writer.write((json.dumps({"ok": True, "values": values}) + "\n").encode())
                await writer.drain()
                return
            if payload.get("type") == "health":
                writer.write((json.dumps({
                    "ok": True, "catalog_id": self.catalog_id, "metrics": self.metrics.__dict__,
                }) + "\n").encode())
                await writer.drain()
                return
            if payload.get("catalog_id") != self.catalog_id:
                writer.write((json.dumps({"ok": False, "error": "catalog_mismatch"}) + "\n").encode())
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

    async def _run_worker(self) -> None:
        while not self._closed:
            request, future = await self.queue.get()
            try:
                if future.cancelled():
                    continue
                result = await asyncio.to_thread(self._apply, request)
                future.set_result(result)
            except Exception as exc:  # noqa: BLE001 - surfaced to client
                if not future.done():
                    future.set_exception(exc)
            finally:
                self.queue.task_done()

    def _apply(self, request: MutationRequest) -> dict[str, Any]:
        payload_hash = self._payload_hash(request)
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
        self.catalog.graph_patch(**patch)
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
                txn.commit()
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
                txn.commit()
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
                txn.commit()
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

    @staticmethod
    def _payload_hash(request: MutationRequest) -> str:
        canonical = json.dumps(
            {"kind": request.kind, "patch": request.patch},
            sort_keys=True, separators=(",", ":"), default=str,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class OwnerClient:
    def __init__(self, socket_path: Path, *, catalog_id: str | None = None, timeout: float = 30.0) -> None:
        self.socket_path = socket_path
        self.catalog_id = catalog_id
        self.timeout = timeout

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            reader, writer = await asyncio.open_unix_connection(
                str(self.socket_path), limit=16 * 1024 * 1024
            )
        except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
            raise OwnerUnavailable(str(exc)) from exc
        try:
            writer.write((json.dumps(payload) + "\n").encode())
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=self.timeout)
            if not line:
                raise OwnerUnavailable("owner closed the connection")
            return json.loads(line)
        except asyncio.TimeoutError as exc:
            raise OwnerUnavailable("owner response timed out") from exc
        finally:
            writer.close()
            await writer.wait_closed()

    async def health(self) -> dict[str, Any]:
        response = await self._request({"type": "health"})
        if self.catalog_id is not None and response.get("catalog_id") != self.catalog_id:
            raise OwnerProtocolError("catalog_mismatch")
        return response

    async def read(self, keys: list[dict[str, str]]) -> dict[str, Any]:
        if self.catalog_id is None:
            health = await self._request({"type": "health"})
            self.catalog_id = health.get("catalog_id")
        return await self._request({"type": "read", "keys": keys, "catalog_id": self.catalog_id})

    async def mutate(self, mutation_id: str, patch: dict[str, Any], *, kind: str = "patch") -> dict[str, Any]:
        if self.catalog_id is None:
            health = await self._request({"type": "health"})
            self.catalog_id = health.get("catalog_id")
        response = await self._request({
            "mutation_id": mutation_id,
            "kind": kind,
            "patch": patch,
            "catalog_id": self.catalog_id,
        })
        if response.get("error") == "catalog_mismatch":
            raise OwnerProtocolError("catalog_mismatch")
        return response

    async def mutate_with_retry(
        self,
        mutation_id: str,
        patch: dict[str, Any],
        *,
        kind: str = "patch",
        attempts: int = 5,
        delay: float = 0.1,
    ) -> dict[str, Any]:
        """Retry only transport failures; the id and payload stay identical."""
        for attempt in range(attempts):
            try:
                return await self.mutate(mutation_id, patch, kind=kind)
            except OwnerUnavailable:
                if attempt == attempts - 1:
                    raise
                await asyncio.sleep(delay)
        raise RuntimeError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--dimension", type=int, default=3072)
    parser.add_argument("--max-queue", type=int, default=256)
    args = parser.parse_args()

    async def run() -> None:
        owner = OvergraphOwner(args.path, dimension=args.dimension, socket_path=args.socket, max_queue=args.max_queue)
        await owner.start()
        print(json.dumps({"ready": True, "socket": str(args.socket)}), flush=True)
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await owner.close()

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

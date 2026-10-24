"""Typed errors, owner metrics and the Unix-socket client.

Split from the owner server so the server stays small; the public imports stay
available from :mod:`app.services.overgraph.owner`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


def _require_ok(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("ok") is True:
        return response
    error = response.get("error")
    if error == "catalog_mismatch":
        raise OwnerProtocolError("catalog_mismatch")
    raise OwnerProtocolError(f"owner request failed: {error}")


@dataclass
class MutationRequest:
    mutation_id: str
    patch: dict[str, Any]
    kind: str = "patch"
    enqueued_at: float = field(default_factory=time.monotonic, repr=False)


METRIC_SAMPLES = 1000


def _record_sample(samples: list[float], started: float) -> None:
    samples.append(round(time.perf_counter() - started, 6))
    del samples[:-METRIC_SAMPLES]


@dataclass
class OwnerMetrics:
    applied: int = 0
    duplicates: int = 0
    rejected: int = 0
    conflicts: int = 0
    queue_high_water: int = 0
    wait_seconds: list[float] = field(default_factory=list)
    queue_wait_seconds: list[float] = field(default_factory=list)
    commit_seconds: list[float] = field(default_factory=list)
    sync_seconds: list[float] = field(default_factory=list)
    read_ops: int = 0
    read_objects: int = 0
    read_bytes: int = 0
    read_seconds: list[float] = field(default_factory=list)


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
        response = _require_ok(await self._request({"type": "health"}))
        if self.catalog_id is not None and response.get("catalog_id") != self.catalog_id:
            raise OwnerProtocolError("catalog_mismatch")
        return response

    async def list_nodes(
        self, label: str, *, props: dict[str, Any] | None = None, include_vectors: bool = False,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if self.catalog_id is None:
            health = await self._request({"type": "health"})
            self.catalog_id = health.get("catalog_id")
        response = _require_ok(await self._request({
            "type": "list_nodes", "catalog_id": self.catalog_id, "label": label,
            "props": props or {}, "include_vectors": include_vectors, "limit": limit,
        }))
        return list(response.get("nodes") or [])

    async def query_nodes(
        self, label: str, *, props: dict[str, Any] | None = None,
        include_vectors: bool = False, limit: int = 100, after: int | None = None,
    ) -> dict[str, Any]:
        """Bounded label query with stable node-id pagination."""
        if self.catalog_id is None:
            health = await self._request({"type": "health"})
            self.catalog_id = health.get("catalog_id")
        response = _require_ok(await self._request({
            "type": "query_nodes", "catalog_id": self.catalog_id, "label": label,
            "props": props or {}, "include_vectors": include_vectors,
            "limit": limit, "after": after,
        }))
        return {
            "nodes": list(response.get("nodes") or []),
            "next_cursor": response.get("next_cursor"),
            "read_revision": response.get("read_revision"),
        }

    async def count_nodes(self, label: str) -> int:
        if self.catalog_id is None:
            health = await self._request({"type": "health"})
            self.catalog_id = health.get("catalog_id")
        response = _require_ok(await self._request({
            "type": "count_nodes", "catalog_id": self.catalog_id, "label": label,
        }))
        return int(response.get("count") or 0)

    async def node(self, node_id: int, *, edge_limit: int = 40) -> dict[str, Any] | None:
        if self.catalog_id is None:
            health = await self._request({"type": "health"})
            self.catalog_id = health.get("catalog_id")
        response = _require_ok(await self._request({
            "type": "node", "catalog_id": self.catalog_id,
            "node_id": node_id, "edge_limit": edge_limit,
        }))
        return response.get("node")

    async def neighbors(
        self, node_id: int, *, direction: str = "outgoing",
        labels: list[str] | None = None, limit: int = 50,
    ) -> list[dict[str, Any]]:
        if self.catalog_id is None:
            health = await self._request({"type": "health"})
            self.catalog_id = health.get("catalog_id")
        response = _require_ok(await self._request({
            "type": "neighbors", "catalog_id": self.catalog_id,
            "node_id": node_id, "direction": direction,
            "labels": labels or [], "limit": limit,
        }))
        return list(response.get("nodes") or [])

    async def read(self, keys: list[dict[str, str]], *, include_vectors: bool = False) -> dict[str, Any]:
        if self.catalog_id is None:
            health = await self._request({"type": "health"})
            self.catalog_id = health.get("catalog_id")
        return _require_ok(await self._request({
            "type": "read", "keys": keys, "catalog_id": self.catalog_id,
            "include_vectors": include_vectors,
        }))

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


def load_catalog_id(path: Path) -> str:
    """Stable identity for one catalog directory, surviving owner restarts."""
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


def payload_hash(request: MutationRequest) -> str:
    canonical = json.dumps(
        {"kind": request.kind, "patch": request.patch},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()

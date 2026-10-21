"""Exact provider-decision cache: process L1 + durable OverGraph L2, single-flight.

One catalog directory per process under ``OVERGRAPH_DIR/jev``. It stores completed
provider answers keyed by a SHA-256 over provider, prompt text, bound input,
declared choices and provider cache params. ``wal_sync_mode="immediate"`` because
a cached decision is reused across runs (SWE phase 4, ``cache_policy: exact``).

The engine owns the cache contract and key (`app.swe.cache`); this module only
implements `DecisionCache` against OverGraph.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from overgraph import OverGraph

from app.config import settings
from app.swe.cache import decision_cache_key  # re-export: callers of this module

__all__ = ["JevDecisionCache", "decision_cache_key"]

LABEL = "JevDecisionCacheEntry"
L1_CAPACITY = 256


class _JevCatalog:
    """Thin locked wrapper around the jev cache OverGraph directory."""

    def __init__(self, db: Any, path: Path) -> None:
        self._db = db
        self.path = path
        self._lock = threading.RLock()

    def get(self, key: str) -> Mapping[str, Any] | None:
        with self._lock:
            view = self._db.get_node_by_key(LABEL, key)
        if view is None:
            return None
        props = dict(getattr(view, "props", {}) or {})
        raw = props.get("answer_json")
        if not isinstance(raw, str):
            return None
        answer = json.loads(raw)
        if not isinstance(answer, dict):
            return None
        return answer

    def put(
        self,
        key: str,
        *,
        answer: Mapping[str, Any],
        provider: str,
        prompt_key: str,
    ) -> None:
        props = {
            "provider": provider,
            "prompt_key": prompt_key,
            "choice": answer["choice"],
            "answer_json": json.dumps(
                dict(answer),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        with self._lock:
            self._db.upsert_node([LABEL], key, props=props)

    def close(self) -> None:
        closer = getattr(self._db, "close", None)
        if closer is not None:
            with self._lock:
                closer()


class JevDecisionCache:
    """Exact cache with L1 FIFO, L2 OverGraph and single-flight per key.

    ``resolve`` returns ``(answer, hit)``. Concurrent identical calls share one
    provider call; only the first caller computes.
    """

    def __init__(
        self,
        *,
        root: Path | None = None,
        capacity: int = L1_CAPACITY,
    ) -> None:
        self._root = root
        self._capacity = capacity
        self._l1: dict[str, Mapping[str, Any]] = {}
        self._catalog: _JevCatalog | None = None
        self._open_lock: asyncio.Lock | None = None
        self._inflight: dict[str, asyncio.Future[Mapping[str, Any]]] = {}
        self.l1_hits = 0
        self.l2_hits = 0
        self.misses = 0

    @property
    def root(self) -> Path:
        if self._root is not None:
            return self._root
        base = Path(settings.overgraph_dir)
        if not base.is_absolute():
            base = Path.cwd() / base
        return base / "jev"

    async def resolve(
        self,
        key: str,
        compute: Callable[[], Awaitable[Mapping[str, Any]]],
        *,
        provider: str,
        prompt_key: str,
    ) -> tuple[Mapping[str, Any], bool]:
        hit = self._l1.get(key)
        if hit is not None:
            self.l1_hits += 1
            return hit, True
        hit = await self._l2_get(key)
        if hit is not None:
            self.l2_hits += 1
            self._l1_put(key, hit)
            return hit, True
        pending = self._inflight.get(key)
        if pending is not None:
            return await asyncio.shield(pending), True
        future: asyncio.Future[Mapping[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._inflight[key] = future
        try:
            answer = dict(await compute())
            self.misses += 1
            self._l1_put(key, answer)
            await self._l2_put(key, answer=answer, provider=provider, prompt_key=prompt_key)
            future.set_result(answer)
            return answer, False
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()
            raise
        finally:
            if self._inflight.get(key) is future:
                del self._inflight[key]

    async def close(self) -> None:
        catalog = self._catalog
        self._catalog = None
        if catalog is not None:
            await asyncio.to_thread(catalog.close)

    def _l1_put(self, key: str, answer: Mapping[str, Any]) -> None:
        self._l1[key] = answer
        while len(self._l1) > self._capacity:
            del self._l1[next(iter(self._l1))]

    async def _l2_get(self, key: str) -> Mapping[str, Any] | None:
        catalog = await self._ensure_catalog()
        return await asyncio.to_thread(catalog.get, key)

    async def _l2_put(
        self,
        key: str,
        *,
        answer: Mapping[str, Any],
        provider: str,
        prompt_key: str,
    ) -> None:
        catalog = await self._ensure_catalog()
        await asyncio.to_thread(
            catalog.put,
            key,
            answer=answer,
            provider=provider,
            prompt_key=prompt_key,
        )

    async def _ensure_catalog(self) -> _JevCatalog:
        catalog = self._catalog
        if catalog is not None:
            return catalog
        if self._open_lock is None:
            self._open_lock = asyncio.Lock()
        async with self._open_lock:
            if self._catalog is not None:
                return self._catalog
            self._catalog = await asyncio.to_thread(_open_catalog, self.root)
            return self._catalog


def _open_catalog(root: Path) -> _JevCatalog:
    root.mkdir(parents=True, exist_ok=True)
    db = OverGraph.open(
        str(root),
        create_if_missing=True,
        dense_vector_dimension=1,
        dense_vector_metric="cosine",
        wal_sync_mode="immediate",
        edge_uniqueness=True,
    )
    return _JevCatalog(db, root)

"""Tenant-independent, content-addressed embeddings shared by graph projections."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.graph_v2 import GraphEmbeddingCache
from app.services.knowledge.embeddings import EmbeddingProvider, require_embedding_vectors
from app.services.knowledge.identity import normalize_assertion_text

_LEASE = timedelta(minutes=5)
_WAIT_SECONDS = 0.05


def _cache_identity(
    identity: tuple[str, str, int, str],
    text: str,
) -> tuple[str, str]:
    model, revision, dimension, purpose = identity
    normalized_text = normalize_assertion_text(text)
    text_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    payload = json.dumps(
        [model, revision, dimension, purpose, text_hash],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), text_hash


class GraphEmbeddingCacheProvider:
    """Batch and persist vectors; leases provide single-flight across workers."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        inner: EmbeddingProvider,
        *,
        purpose: str = "text.v1",
        revision: str | None = None,
    ) -> None:
        self._factory = factory
        self._inner = inner
        self._purpose = purpose
        self._revision = revision or getattr(inner, "model_revision", inner.model)
        self._owner = uuid.uuid4().hex
        self._flights: dict[str, asyncio.Future[list[float]]] = {}
        self._lock = asyncio.Lock()

    @property
    def provider_id(self) -> str:
        return self._inner.provider_id

    @property
    def model(self) -> str:
        return self._inner.model

    @property
    def dimension(self) -> int:
        return self._inner.dimension

    @property
    def model_revision(self) -> str:
        return self._revision

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed(texts, session=None)

    async def embed_in_session(
        self,
        session: AsyncSession,
        texts: Sequence[str],
    ) -> list[list[float]]:
        """Keep SQLite cache writes on the graph transaction's connection."""
        if session.bind is not None and session.bind.dialect.name != "sqlite":
            return await self.embed(texts)
        return await self._embed(texts, session=session)

    async def _embed(
        self,
        texts: Sequence[str],
        *,
        session: AsyncSession | None,
    ) -> list[list[float]]:
        if not texts:
            return []
        identities = {
            text: _cache_identity(
                (self.model, self._revision, self.dimension, self._purpose),
                text,
            )
            for text in dict.fromkeys(texts)
        }
        vectors = await self._resolve(identities, session=session)
        return [list(vectors[text]) for text in texts]

    async def _resolve(
        self,
        identities: dict[str, tuple[str, str]],
        *,
        session: AsyncSession | None,
    ) -> dict[str, list[float]]:
        keys = {text: pair[0] for text, pair in identities.items()}
        owned: dict[str, str] = {}
        futures: dict[str, asyncio.Future[list[float]]] = {}

        # Coordinate same-process callers before reserving DB leases.
        async with self._lock:
            for text, key in keys.items():
                future = self._flights.get(key)
                if future is None:
                    future = asyncio.get_running_loop().create_future()
                    future.add_done_callback(_consume_future_error)
                    self._flights[key] = future
                    owned[text] = key
                futures[text] = future

        try:
            if owned:
                await self._fill(owned, identities, session=session)
            return {text: await asyncio.shield(future) for text, future in futures.items()}
        except BaseException as exc:
            async with self._lock:
                for key in owned.values():
                    future = self._flights.pop(key, None)
                    if future is not None and not future.done():
                        future.set_exception(exc)
            raise

    async def _reserve(
        self,
        owned: dict[str, str],
        identities: dict[str, tuple[str, str]],
        *,
        session: AsyncSession | None,
    ) -> tuple[dict[str, list[float]], dict[str, str]]:
        if session is not None:
            return await self._reserve_rows(session, owned, identities)
        async with self._factory.begin() as cache_session:
            return await self._reserve_rows(cache_session, owned, identities)

    async def _reserve_rows(
        self,
        session: AsyncSession,
        owned: dict[str, str],
        identities: dict[str, tuple[str, str]],
    ) -> tuple[dict[str, list[float]], dict[str, str]]:
        cache_hits: dict[str, list[float]] = {}
        reserved: dict[str, str] = {}
        now = datetime.now(UTC)
        for text, key in owned.items():
            text_hash = identities[text][1]
            row = await session.scalar(
                select(GraphEmbeddingCache).where(GraphEmbeddingCache.key == key).with_for_update()
            )
            if row is None:
                row = GraphEmbeddingCache(
                    key=key,
                    model=self.model,
                    model_revision=self._revision,
                    dimension=self.dimension,
                    purpose=self._purpose,
                    normalized_text_hash=text_hash,
                    status="pending",
                    lock_owner=self._owner,
                    lock_expires_at=now + _LEASE,
                )
                try:
                    async with session.begin_nested():
                        session.add(row)
                        await session.flush()
                    reserved[text] = key
                    continue
                except IntegrityError:
                    row = await session.scalar(
                        select(GraphEmbeddingCache)
                        .where(GraphEmbeddingCache.key == key)
                        .with_for_update()
                    )
            if row is None:
                raise RuntimeError("embedding cache reservation disappeared")
            if row.status == "ready" and row.vector is not None:
                row.last_used_at = now
                cache_hits[text] = list(row.vector)
            elif row.lock_owner == self._owner:
                reserved[text] = key
            elif _lease_expired(row.lock_expires_at, now):
                row.status = "pending"
                row.lock_owner = self._owner
                row.lock_expires_at = now + _LEASE
                row.last_error = None
                reserved[text] = key
        return cache_hits, reserved

    async def _fill(
        self,
        owned: dict[str, str],
        identities: dict[str, tuple[str, str]],
        *,
        session: AsyncSession | None,
    ) -> None:
        pending = dict(owned)
        resolved: dict[str, list[float]] = {}
        while pending:
            # Rows reserved by another process are awaited; expired reservations are reclaimed.
            hits, reserved = await self._reserve(pending, identities, session=session)
            resolved.update(hits)
            if reserved:
                texts = list(reserved)
                try:
                    vectors = require_embedding_vectors(
                        await self._inner.embed([normalize_assertion_text(text) for text in texts]),
                        dimension=self.dimension,
                    )
                    if len(vectors) != len(texts):
                        raise RuntimeError("EmbeddingProvider returned an unexpected vector count")
                except BaseException as exc:
                    if session is None:
                        async with self._factory.begin() as cache_session:
                            await self._release(cache_session, reserved, exc)
                    else:
                        await self._release(session, reserved, exc)
                    raise
                if session is None:
                    async with self._factory.begin() as cache_session:
                        await self._store(
                            cache_session,
                            {
                                text: (reserved[text], vector)
                                for text, vector in zip(texts, vectors, strict=True)
                            },
                            resolved,
                        )
                else:
                    await self._store(
                        session,
                        {
                            text: (reserved[text], vector)
                            for text, vector in zip(texts, vectors, strict=True)
                        },
                        resolved,
                    )
            pending = {text: key for text, key in pending.items() if text not in resolved}
            if pending:
                await asyncio.sleep(_WAIT_SECONDS)
        async with self._lock:
            for text, key in owned.items():
                future = self._flights.pop(key, None)
                if future is not None and not future.done():
                    future.set_result(resolved[text])

    async def _release(
        self,
        session: AsyncSession,
        reserved: dict[str, str],
        exc: BaseException,
    ) -> None:
        for key in reserved.values():
            await session.execute(
                update(GraphEmbeddingCache)
                .where(
                    GraphEmbeddingCache.key == key,
                    GraphEmbeddingCache.lock_owner == self._owner,
                    GraphEmbeddingCache.status == "pending",
                )
                .values(lock_owner=None, lock_expires_at=None, last_error=str(exc)[:1000])
            )

    async def _store(
        self,
        session: AsyncSession,
        entries: dict[str, tuple[str, list[float]]],
        resolved: dict[str, list[float]],
    ) -> None:
        for text, (key, vector) in entries.items():
            await session.execute(
                update(GraphEmbeddingCache)
                .where(
                    GraphEmbeddingCache.key == key,
                    GraphEmbeddingCache.lock_owner == self._owner,
                    GraphEmbeddingCache.status == "pending",
                )
                .values(
                    vector=vector,
                    status="ready",
                    lock_owner=None,
                    lock_expires_at=None,
                    last_error=None,
                    last_used_at=datetime.now(UTC),
                )
            )
            resolved[text] = vector


def _lease_expired(expires_at: datetime | None, now: datetime) -> bool:
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= now


def _consume_future_error(future: asyncio.Future[list[float]]) -> None:
    if not future.cancelled():
        future.exception()

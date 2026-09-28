"""Embedding provider for knowledge ingest and search. VectorStore does not create vectors."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from openai import AsyncOpenAI

from app.config import EMBEDDING_MODEL_DIMENSIONS, settings

# OpenAI embeddings API batch limit.
_MAX_BATCH = 2048
DEFAULT_EMBEDDING_CACHE_ENTRIES = 2048


class EmbeddingProvider(Protocol):
    provider_id: str
    model: str
    dimension: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class EmbeddingSpec:
    """Model and index dimension are one configuration, not independent defaults."""

    model: str
    dimension: int

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("embedding model must not be empty")
        if self.dimension < 1:
            raise ValueError("embedding dimension must be >= 1")
        known = EMBEDDING_MODEL_DIMENSIONS.get(self.model)
        if known is not None and known != self.dimension:
            raise ValueError(
                f"Embedding model {self.model!r} requires dimension {known}, got {self.dimension}"
            )


def require_embedding_vectors(
    vectors: Sequence[Sequence[float]],
    *,
    dimension: int,
) -> list[list[float]]:
    out: list[list[float]] = []
    for index, vector in enumerate(vectors):
        if len(vector) != dimension:
            raise RuntimeError(
                f"embedding[{index}] has dimension {len(vector)}, expected {dimension}"
            )
        out.append(list(vector))
    return out


class CachingEmbeddingProvider:
    """In-process cache in front of an EmbeddingProvider. Same text, same vector."""

    def __init__(
        self,
        inner: EmbeddingProvider,
        *,
        max_entries: int = DEFAULT_EMBEDDING_CACHE_ENTRIES,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._inner = inner
        self._max_entries = max_entries
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[list[float]]] = {}
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

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        owned, waiters = await self._claim_texts(texts)
        if owned:
            await self._fill_owned(owned)
        resolved: dict[str, list[float]] = {}
        for text, future in waiters.items():
            resolved[text] = await future
        async with self._lock:
            for text in texts:
                if text not in resolved:
                    resolved[text] = self._cache[text]
        return [list(resolved[text]) for text in texts]

    async def _claim_texts(
        self, texts: Sequence[str]
    ) -> tuple[list[str], dict[str, asyncio.Future[list[float]]]]:
        owned: list[str] = []
        waiters: dict[str, asyncio.Future[list[float]]] = {}
        async with self._lock:
            for text in dict.fromkeys(texts):
                cached = self._cache.get(text)
                if cached is not None:
                    self._cache.move_to_end(text)
                    continue
                existing = self._inflight.get(text)
                if existing is not None:
                    waiters[text] = existing
                    continue
                future: asyncio.Future[list[float]] = asyncio.get_running_loop().create_future()
                self._inflight[text] = future
                waiters[text] = future
                owned.append(text)
        return owned, waiters

    async def _fill_owned(self, owned: list[str]) -> None:
        try:
            vectors = await self._inner.embed(owned)
            if len(vectors) != len(owned):
                raise RuntimeError("EmbeddingProvider returned an unexpected vector count")
        except BaseException as exc:
            await self._fail_owned(owned, exc)
            raise
        async with self._lock:
            for text, vector in zip(owned, vectors, strict=True):
                copied = list(vector)
                self._cache[text] = copied
                self._cache.move_to_end(text)
                future = self._inflight.pop(text, None)
                if future is not None and not future.done():
                    future.set_result(copied)
            while len(self._cache) > self._max_entries:
                self._cache.popitem(last=False)

    async def _fail_owned(self, owned: list[str], exc: BaseException) -> None:
        async with self._lock:
            for text in owned:
                future = self._inflight.pop(text, None)
                if future is not None and not future.done():
                    future.set_exception(exc)


class OpenAIEmbeddingProvider:
    """OpenAI embeddings, batched. Isolated from the SSR cache/client."""

    provider_id = "openai"

    def __init__(
        self,
        *,
        model: str,
        dimension: int,
        client: AsyncOpenAI | None = None,
        batch_size: int = _MAX_BATCH,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        spec = EmbeddingSpec(model=model, dimension=dimension)
        self.model = spec.model
        self.dimension = spec.dimension
        self._client = client
        self._batch_size = min(batch_size, _MAX_BATCH)

    @classmethod
    def from_settings(cls, *, client: AsyncOpenAI | None = None) -> OpenAIEmbeddingProvider:
        return cls(
            model=settings.embedding_model,
            dimension=settings.embedding_dimension,
            client=client,
        )

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        client = self._client or _openai_client()
        out: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = [
                text if text.strip() else " " for text in texts[start : start + self._batch_size]
            ]
            response = await client.embeddings.create(model=self.model, input=batch)
            by_index = {row.index: row.embedding for row in response.data}
            for index in range(len(batch)):
                vector = by_index.get(index)
                if vector is None:
                    raise RuntimeError(f"embedding response missing index {index}")
                out.append(list(vector))
        return require_embedding_vectors(out, dimension=self.dimension)


def _openai_client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.embedding_base_url,
        timeout=settings.embedding_timeout_seconds,
    )

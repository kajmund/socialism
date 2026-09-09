"""Embedding provider for knowledge ingest and search. VectorStore does not create vectors."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from openai import AsyncOpenAI

from app.config import EMBEDDING_MODEL_DIMENSIONS, settings

# OpenAI embeddings API batch limit.
_MAX_BATCH = 2048


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
            batch = [text if text.strip() else " " for text in texts[start : start + self._batch_size]]
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

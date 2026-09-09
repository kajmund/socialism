"""Embedding provider for knowledge ingest. VectorStore does not create vectors."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from openai import AsyncOpenAI

from app.config import settings

# OpenAI embeddings API batch limit.
_MAX_BATCH = 2048
_TEXT_EMBEDDING_3_LARGE_DIMS = 3072


class EmbeddingProvider(Protocol):
    provider_id: str
    dimension: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class OpenAIEmbeddingProvider:
    """OpenAI embeddings, batched. Isolated from the SSR cache/client."""

    provider_id = "openai"
    dimension = _TEXT_EMBEDDING_3_LARGE_DIMS

    def __init__(
        self,
        *,
        client: AsyncOpenAI | None = None,
        model: str | None = None,
        batch_size: int = _MAX_BATCH,
        dimension: int = _TEXT_EMBEDDING_3_LARGE_DIMS,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self._client = client
        self._model = model
        self._batch_size = min(batch_size, _MAX_BATCH)
        self.dimension = dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        client = self._client or _openai_client()
        model = self._model or settings.embedding_model
        out: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = [text if text.strip() else " " for text in texts[start : start + self._batch_size]]
            response = await client.embeddings.create(model=model, input=batch)
            by_index = {row.index: row.embedding for row in response.data}
            for index in range(len(batch)):
                vector = by_index.get(index)
                if vector is None:
                    raise RuntimeError(f"embedding response missing index {index}")
                out.append(list(vector))
        return out


def _openai_client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.embedding_base_url,
        timeout=settings.embedding_timeout_seconds,
    )

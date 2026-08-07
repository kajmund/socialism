"""OpenAI embeddings client (separate from DeepSeek chat)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from openai import AsyncOpenAI

from app.config import settings

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]

_client: AsyncOpenAI | None = None
_embedder: Embedder | None = None

# OpenAI embedding API batch limit.
_MAX_BATCH = 2048


def get_embedding_client() -> AsyncOpenAI:
    """Client bound to settings — never reads CAMEL's mirrored OPENAI_API_KEY env."""
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.embedding_base_url,
            timeout=settings.embedding_timeout_seconds,
        )
    return _client


def reset_embedding_client() -> None:
    global _client
    _client = None


def set_embedder(embedder: Embedder | None) -> None:
    global _embedder
    _embedder = embedder


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if _embedder is not None:
        return await _embedder(texts)
    if not texts:
        return []
    client = get_embedding_client()
    out: list[list[float]] = []
    for start in range(0, len(texts), _MAX_BATCH):
        chunk = texts[start : start + _MAX_BATCH]
        # Empty strings break the API — normalize.
        cleaned = [t if t.strip() else " " for t in chunk]
        response = await client.embeddings.create(
            model=settings.embedding_model,
            input=cleaned,
        )
        by_index = {row.index: row.embedding for row in response.data}
        for i in range(len(cleaned)):
            vec = by_index.get(i)
            if vec is None:
                raise RuntimeError(f"embedding response missing index {i}")
            out.append(list(vec))
    return out

"""Test doubles for knowledge embeddings. Token overlap so cosine search works."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

FAKE_EMBED_DIM = 32


def fake_embed_text(text: str, *, dimension: int = FAKE_EMBED_DIM) -> list[float]:
    vector = [0.0] * dimension
    for word in text.lower().split():
        index = int(hashlib.sha256(word.encode()).hexdigest(), 16) % dimension
        vector[index] += 1.0
    return vector


class FakeEmbeddingProvider:
    provider_id = "fake"
    model = "fake-tokens"
    dimension = FAKE_EMBED_DIM

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail = False

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(tuple(texts))
        if self.fail:
            raise RuntimeError("embedding failed")
        return [fake_embed_text(text, dimension=self.dimension) for text in texts]

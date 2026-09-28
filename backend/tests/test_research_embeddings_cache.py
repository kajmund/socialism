"""Research composition shares one CachingEmbeddingProvider."""

from __future__ import annotations

from app.services.knowledge.embeddings import CachingEmbeddingProvider
from app.services.research.composition import (
    research_embeddings,
    reset_research_embeddings,
)


def test_research_embeddings_are_shared_and_resettable():
    reset_research_embeddings()
    first = research_embeddings()
    second = research_embeddings()
    assert isinstance(first, CachingEmbeddingProvider)
    assert first is second
    reset_research_embeddings()
    third = research_embeddings()
    assert third is not first
    reset_research_embeddings()

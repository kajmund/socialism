"""Research composition shares one persistent Graph embedding cache."""

from __future__ import annotations

from app.services.graph_v2.embeddings import GraphEmbeddingCacheProvider
from app.services.research.composition import (
    research_embeddings,
    reset_research_embeddings,
)


def test_research_embeddings_are_shared_and_resettable():
    reset_research_embeddings()
    first = research_embeddings()
    second = research_embeddings()
    assert isinstance(first, GraphEmbeddingCacheProvider)
    assert first is second
    assert first.model_revision
    reset_research_embeddings()
    third = research_embeddings()
    assert third is not first
    reset_research_embeddings()

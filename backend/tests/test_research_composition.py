"""Standard ResearchRouter composition seams. No session-bound preflight."""

from __future__ import annotations

import pytest

from app.services.research.composition import (
    ResearchCompositionError,
    require_research_router_ready,
    set_knowledge_vector_store_factory,
    set_research_router_factory,
)


def test_require_research_router_ready_does_not_build_router():
    def boom(_session):
        raise AssertionError("require must not construct a session-bound router")

    set_research_router_factory(boom)
    try:
        require_research_router_ready()
    finally:
        set_research_router_factory(None)


def test_require_research_router_ready_accepts_vector_store_seam():
    set_research_router_factory(None)
    set_knowledge_vector_store_factory(lambda: object())
    try:
        require_research_router_ready()
    finally:
        set_knowledge_vector_store_factory(None)


def test_require_research_router_ready_fails_when_unconfigured():
    set_research_router_factory(None)
    set_knowledge_vector_store_factory(None)
    with pytest.raises(ResearchCompositionError, match="KnowledgeVectorStore"):
        require_research_router_ready()

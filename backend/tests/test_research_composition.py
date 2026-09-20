"""Standard ResearchRouter composition seams. No session-bound preflight."""

from __future__ import annotations

import pytest

from app.services.research.composition import (
    ResearchCompositionError,
    require_research_router_ready,
    set_knowledge_vector_store_factory,
    set_research_router_factory,
    standard_available_source_types,
)
from app.services.research.provider import knowledge_adapter_descriptor
from app.services.research.registry import (
    default_standard_capability_descriptors,
    production_registered_source_types,
    set_standard_capability_descriptors,
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


def test_standard_available_source_types_follow_capability_descriptors():
    set_standard_capability_descriptors(
        (
            *default_standard_capability_descriptors(),
            knowledge_adapter_descriptor("synthetic-provider", "web"),
        )
    )
    try:
        offered = standard_available_source_types()
        assert offered == production_registered_source_types()
        assert "web" in offered
        assert "swedish_law" in offered
        assert "case_knowledge" not in offered
        assert "customer_knowledge" not in offered
    finally:
        set_standard_capability_descriptors(None)
    assert "web" not in standard_available_source_types()
    assert "swedish_law" in standard_available_source_types()

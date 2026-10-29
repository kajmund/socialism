"""Owner fact writer validation: fail closed and stay tenant scoped."""

from __future__ import annotations

import pytest

from app.services.graph_v2.errors import PermanentGraphError
from app.services.graph_v2.types import FactInput, SourceRef
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.labels import CONTRADICTS, ENTITY, FACT, scope_label
from app.services.overgraph.owner_facts import write_fact_via_owner
from app.services.overgraph.owner_runtime import get_owner_runtime

SEED_ID = "seed-fact-validation"


def _entity(key: str, scope) -> dict:
    return {
        "labels": [ENTITY, scope_label(scope.scope_key)],
        "key": key,
        "props": {"scope_key": scope.scope_key, "node_type": "org", "name": key},
    }


async def _seed():
    scope = customer_scope(1)
    foreign = customer_scope(2)
    client = get_owner_runtime().require_client()
    await client.mutate(
        SEED_ID,
        {"upsert_nodes": [
            _entity("src", scope),
            _entity("dst", scope),
            _entity("foreign", foreign),
            {
                "labels": ["TextUnit", scope_label(scope.scope_key)],
                "key": "u1",
                "props": {
                    "scope_key": scope.scope_key,
                    "text": "text",
                    "content_hash": "u1",
                    "document_id": "doc",
                    "document_version_id": "ver",
                },
            },
        ]},
        kind="batch",
    )
    return scope


def _fact(scope, *, source="src", target="dst", unit="u1") -> FactInput:
    return FactInput(
        source_id=source,
        target_id=target,
        scope=scope,
        predicate="legal.has",
        fact_text="Avtalet har uppsägningstid.",
        sources=(SourceRef("text_unit", unit),),
        occurrence_key="occ",
    )


async def test_missing_text_unit_fails_without_writing():
    scope = await _seed()
    client = get_owner_runtime().require_client()
    with pytest.raises(PermanentGraphError):
        await write_fact_via_owner(client, _fact(scope, unit="missing"))
    assert require_knowledge().count_nodes_by_labels([FACT]) == 0


async def test_missing_endpoint_fails_without_writing():
    scope = await _seed()
    client = get_owner_runtime().require_client()
    with pytest.raises(PermanentGraphError):
        await write_fact_via_owner(client, _fact(scope, target="ghost"))
    assert require_knowledge().count_nodes_by_labels([FACT]) == 0


async def test_cross_tenant_endpoint_is_rejected():
    scope = await _seed()
    client = get_owner_runtime().require_client()
    with pytest.raises(PermanentGraphError):
        await write_fact_via_owner(client, _fact(scope, target="foreign"))
    assert require_knowledge().count_nodes_by_labels([FACT]) == 0


async def test_missing_contradiction_target_is_skipped_like_direct_writer():
    scope = await _seed()
    client = get_owner_runtime().require_client()
    result = await write_fact_via_owner(
        client, _fact(scope), contradiction_key="does-not-exist",
    )
    assert result["result"]["ok"] is True
    assert require_knowledge().count_edges_by_label(CONTRADICTS) == 0

"""Saved-result lookup: identity, temporality, scope, evidence and stable ordering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.labels import FACT
from app.services.overgraph.research import update_fact
from app.services.research.answer_graph import ANSWER_PREDICATE
from app.services.research.result_store import exact_answers, load_saved_answer
from tests.research_reuse.helpers import MAIN, context, need
from tests.research_reuse.test_completed_result import ready_result

pytestmark = pytest.mark.research_reuse


async def _answer_fact_id(session) -> str:
    """The answer fact id, read from OverGraph (the authoritative graph)."""
    from app.services.overgraph.catalogs import require_knowledge
    from app.services.overgraph.labels import ENTITY, FACT, scope_label

    catalog = require_knowledge()
    nodes, _ = catalog.query_nodes(
        label_filter={"labels": [FACT, scope_label("customer:1")], "mode": "all"}, limit=200,
    )
    for node in nodes:
        if str(node.props.get("predicate") or "") != ANSWER_PREDICATE:
            continue
        target = catalog.get_by_key(ENTITY, str(node.props.get("target_key") or ""))
        if target is not None and str(target.props.get("name") or "") == MAIN:
            return str(node.key)
    raise AssertionError("the answer fact must exist in OverGraph")


async def test_result_is_reachable_by_question_identity_and_by_fact_id(reuse_db):
    await ready_result(reuse_db)
    scope = context()
    now = datetime.now(UTC)
    async with reuse_db() as session:
        fact_id = await _answer_fact_id(session)
        by_identity = await exact_answers(session, need(question=MAIN), scope, now=now)
        saved = await load_saved_answer(session, fact_id, scope, now=now)
    assert by_identity == [fact_id]
    assert saved is not None
    assert saved.fact_id == fact_id
    assert saved.question_id
    assert saved.question == MAIN


async def test_saved_result_carries_basis_and_question_identity(reuse_db):
    await ready_result(reuse_db)
    scope = context()
    async with reuse_db() as session:
        fact_id = await _answer_fact_id(session)
        saved = await load_saved_answer(session, fact_id, scope, now=datetime.now(UTC))
    assert saved is not None
    assert saved.basis, "resumed answer lost its evidence basis"
    assert saved.evidence_set_id
    assert saved.assessment.get("sufficient") is True
    assert saved.context["objective"] is not None


async def test_invalidated_answer_is_not_returned_by_identity_or_by_fact_id(reuse_db):
    await ready_result(reuse_db)
    scope = context()
    now = datetime.now(UTC)
    async with reuse_db() as session:
        fact_id = await _answer_fact_id(session)
    update_fact(require_knowledge(), fact_id, status="invalidated", invalid_at=now - timedelta(days=1))
    async with reuse_db() as session:
        assert await exact_answers(session, need(question=MAIN), scope, now=now) == []
        assert await load_saved_answer(session, fact_id, scope, now=now) is None


async def test_not_yet_valid_answer_is_not_returned(reuse_db):
    await ready_result(reuse_db)
    scope = context()
    now = datetime.now(UTC)
    async with reuse_db() as session:
        fact_id = await _answer_fact_id(session)
    update_fact(require_knowledge(), fact_id, valid_at=now + timedelta(days=1))
    async with reuse_db() as session:
        assert await exact_answers(session, need(question=MAIN), scope, now=now) == []
        assert await load_saved_answer(session, fact_id, scope, now=now) is None


async def test_another_customer_does_not_reach_the_saved_result(reuse_db):
    await ready_result(reuse_db)
    now = datetime.now(UTC)
    async with reuse_db() as session:
        fact_id = await _answer_fact_id(session)
        assert await exact_answers(
            session, need(question=MAIN), context(customer_id=2), now=now,
        ) == []
        assert (
            await load_saved_answer(
                session, fact_id, context(customer_id=2), now=now,
            )
            is None
        )


async def test_exact_answers_are_unique_and_newest_first(reuse_db):
    await ready_result(reuse_db)
    now = datetime.now(UTC)
    async with reuse_db() as session:
        ids = await exact_answers(session, need(question=MAIN), context(), now=now)
    assert len(ids) == len(set(ids)), "answer ids must not repeat"
    catalog = require_knowledge()
    stamps = [int(catalog.get_by_key(FACT, fact_id).props["created_at_ms"]) for fact_id in ids]
    assert stamps == sorted(stamps, reverse=True)


async def test_exact_answers_stop_at_eight_without_dropping_current_answers(reuse_db):
    await ready_result(reuse_db)
    now = datetime.now(UTC)
    async with reuse_db() as session:
        ids = await exact_answers(session, need(question=MAIN), context(), now=now)
    assert len(ids) <= 8


async def test_multiple_evidence_sources_lose_the_answer_only_when_a_referenced_fact_breaks(reuse_db):
    """One invalidated dependency invalidates the answer; a smaller frozen basis still works."""
    import json

    from app.services.graph_v2.types import FactInput, NodeInput
    from app.services.knowledge.scope import customer_scope
    from app.services.overgraph.labels import ENTITY
    from app.services.overgraph.research import update_fact
    from app.services.overgraph.write import upsert_entity, write_fact

    await ready_result(reuse_db)
    scope = context()
    now = datetime.now(UTC)
    catalog = require_knowledge()
    async with reuse_db() as session:
        fact_id = await _answer_fact_id(session)

    def entity(key: str) -> str:
        return upsert_entity(catalog, NodeInput(
            node_type="core.concept", name=key, scope=customer_scope(scope.scope.customer_id),
        )).key

    left, right = entity("dep-left"), entity("dep-right")
    dep_scope = customer_scope(scope.scope.customer_id)
    for dep_id, endpoint in (("dep-1", left), ("dep-2", right)):
        write_fact(catalog, FactInput(
            source_id=left, target_id=endpoint, scope=dep_scope,
            predicate="research.support", fact_text=f"support {dep_id}", sources=(),
        ), key=dep_id)

    node = catalog.get_by_key(ENTITY, str(catalog.get_by_key(FACT, fact_id).props["target_key"]))
    attributes = json.loads(str(node.props["attributes_json"]))
    attributes["basis"][0]["metadata"]["graph_fact_ids"] = ["dep-1", "dep-2"]
    props = dict(node.props)
    props["attributes_json"] = json.dumps(attributes, ensure_ascii=False, sort_keys=True)
    catalog.upsert_node(list(node.labels), node.key, props=props)

    async with reuse_db() as session:
        assert await load_saved_answer(session, fact_id, scope, now=now) is not None

    update_fact(catalog, "dep-1", invalid_at=now - timedelta(days=1))
    async with reuse_db() as session:
        assert await load_saved_answer(session, fact_id, scope, now=now) is None

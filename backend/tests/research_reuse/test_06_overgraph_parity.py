"""Answer publication must land in OverGraph, not only in the SQL graph mirror.

The reader migration (step 2) is only safe while every legacy writer still mirrors
into OverGraph. This pins the answer path: the outbox-independent `publish_answer`
must produce the same answer fact in the authoritative graph.
"""

import json

import pytest

from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.labels import ENTITY, FACT, scope_label
from app.services.overgraph.research import QUESTION_TYPE
from app.services.research.answer_graph import ANSWER_PREDICATE
from app.services.research.answer_review import capture_answer_reviews
from tests.research_reuse.test_04_main_answer import persisted_basis

pytestmark = pytest.mark.research_reuse


async def test_every_published_answer_fact_is_present_in_overgraph(reuse_db):
    attempt_id, set_id = await persisted_basis(reuse_db)
    async with reuse_db.begin() as session:
        await capture_answer_reviews(session, attempt_id=attempt_id, evidence_set_id=set_id)

    catalog = require_knowledge()
    facts, _ = catalog.query_nodes(
        label_filter={"labels": [FACT, scope_label("customer:1")], "mode": "all"}, limit=200,
    )
    answers = [
        row for row in facts
        if str(row.props.get("predicate") or "") == ANSWER_PREDICATE
    ]
    assert answers, "the answer path published no fact"

    for row in answers:
        assert str(row.props.get("status") or "") == "active"
        target = catalog.get_by_key(ENTITY, str(row.props.get("target_key") or ""))
        assert target is not None, "answer fact lost its answer node"
        target_attributes = json.loads(str(target.props.get("attributes_json") or "{}"))
        assert target_attributes.get("evidence_set_id") == set_id
        question = catalog.get_by_key(ENTITY, str(row.props.get("source_key") or ""))
        assert question is not None, "answer fact lost its question node"
        assert str(question.props.get("node_type") or "") == QUESTION_TYPE
        question_attrs = json.loads(str(question.props.get("attributes_json") or "{}"))
        assert question_attrs.get("canonical_question_id")

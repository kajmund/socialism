"""Reuse payload projection reads the answer from OverGraph with its frozen basis."""

from __future__ import annotations

import pytest

from app.services.execution import attach_evidence_set, create_evidence_set
from app.services.execution.reuse_reference import REUSE_KEY
from app.services.execution.reuse_views import reuse_payloads
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.publish import AnswerPublish, publish_answer_fact
from tests.research_reuse.helpers import MAIN, attempt

pytestmark = pytest.mark.research_reuse


def _publish(*, fact_id: str, evidence_set_id: str, customer_id: int = 1, basis=None) -> None:
    publish_answer_fact(
        require_knowledge(),
        AnswerPublish(
            question_id=f"question-{customer_id}",
            question_text=MAIN,
            scope=customer_scope(customer_id),
            identity=f"answer-{fact_id}",
            evidence_set_id=evidence_set_id,
            fact_id=fact_id,
            attributes={"knowledge_module": "dd", "answer_status": "sufficient"},
            basis=basis or [{"evidence_id": "ev-1", "title": "36 §"}],
            assessment={"sufficient": True},
            dependency_ids=(),
        ),
    )


async def _attempt_with_reuse(reuse_db, *, fact_id: str, customer_id: int = 1):
    async with reuse_db.begin() as session:
        row = await attempt(session)
        frozen = await create_evidence_set(session, run_id=row.run_id)
        await attach_evidence_set(session, attempt_id=row.id, evidence_set_id=frozen.id)
        row.input_snapshot = {
            **row.input_snapshot,
            REUSE_KEY: {"answer_fact_id": fact_id, "need_id": "child", "question": MAIN},
        }
        await session.flush()
        return row.id, frozen.id, row.run_id


async def test_reuse_payload_comes_from_overgraph_with_its_basis(reuse_db):
    attempt_id, set_id, _run_id = await _attempt_with_reuse(reuse_db, fact_id="fact-1")
    _publish(fact_id="fact-1", evidence_set_id=set_id)
    async with reuse_db() as session:
        from app.database.models import ExecutionAttempt

        row = await session.get(ExecutionAttempt, attempt_id)
        payloads = await reuse_payloads(session, [row])
    assert len(payloads) == 1
    _attempt, ref, payload = payloads[0]
    assert ref["answer_fact_id"] == "fact-1"
    assert payload["evidence_set_id"] == set_id
    assert payload["basis"][0]["evidence_id"] == "ev-1"
    assert payload["assessment"]["sufficient"] is True


async def test_reuse_payload_rejects_a_mismatched_frozen_set(reuse_db):
    attempt_id, set_id, _run_id = await _attempt_with_reuse(reuse_db, fact_id="fact-2")
    _publish(fact_id="fact-2", evidence_set_id=f"{set_id}-other")
    async with reuse_db() as session:
        from app.database.models import ExecutionAttempt

        row = await session.get(ExecutionAttempt, attempt_id)
        with pytest.raises(RuntimeError, match="does not match its frozen result"):
            await reuse_payloads(session, [row])


async def test_reuse_payload_rejects_another_tenant_answer(reuse_db):
    attempt_id, set_id, _run_id = await _attempt_with_reuse(reuse_db, fact_id="fact-3")
    _publish(fact_id="fact-3", evidence_set_id=set_id, customer_id=2)
    async with reuse_db() as session:
        from app.database.models import ExecutionAttempt

        row = await session.get(ExecutionAttempt, attempt_id)
        with pytest.raises(RuntimeError, match="does not match its frozen result"):
            await reuse_payloads(session, [row])


async def test_reuse_payload_rejects_a_missing_answer(reuse_db):
    attempt_id, set_id, _run_id = await _attempt_with_reuse(reuse_db, fact_id="fact-absent")
    _publish(fact_id="fact-4", evidence_set_id=set_id)
    async with reuse_db() as session:
        from app.database.models import ExecutionAttempt

        row = await session.get(ExecutionAttempt, attempt_id)
        with pytest.raises(RuntimeError, match="does not match its frozen result"):
            await reuse_payloads(session, [row])

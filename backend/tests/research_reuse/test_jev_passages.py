import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from app.jev.system import JevClientError, JevSystemOneResult, JevUsage
from app.services.research.evidence_screen import EVIDENCE_SCREEN_QUESTIONS
from app.services.research.assessment import AssessableEvidence
from app.services.research.reuse_gate import assessable_candidates
from tests.research_reuse.jev_controls import snapshots
from tests.research_reuse.jev_passages import measure, requests
from tests.research_reuse.snapshots import EVIDENCE, digest

pytestmark = pytest.mark.research_reuse


def control_items() -> list[AssessableEvidence]:
    return assessable_candidates(EVIDENCE.validate_python(snapshots()[-1]["evidence"]))


def response(questions: dict, *, model: str = "fixed", value: object = 0.8) -> JevSystemOneResult:
    return JevSystemOneResult(
        answers={key: {"noul": value} for key in questions}, model=model,
        latency_ms=10, input_chars=100, usage=JevUsage(), raw={},
    )


def test_full_and_batched_keep_exact_text_hash_and_target_bindings():
    items = control_items()
    before = digest([item.excerpt for item in items])
    for variant in ("full", "batched"):
        planned = requests(items, objective="question", variant=variant)
        rows = [row for request in planned for row in request.state["evidence"]]
        assert [row["excerpt"] for row in rows] == [item.excerpt for item in items]
        assert [row["content_hash"] for row in rows] == [item.content_hash for item in items]
        assert sum(len(request.bindings) for request in planned) == 12
        if variant == "batched":
            for key, (evidence_id, _) in planned[0].bindings.items():
                assert planned[0].questions[key]["instructions"]["evidence"]["evidence_id"] == evidence_id
    assert before == digest([item.excerpt for item in items])
    assert isinstance(EVIDENCE_SCREEN_QUESTIONS["relevant_to_question"]["instructions"], str)


def test_compact_is_the_existing_payload_and_omits_late_control_fact():
    planned = requests(control_items(), objective="question", variant="compact")
    assert len(planned) == 2
    assert len(planned[0].state["evidence"]["excerpt"]) == 280
    assert "1 maj" not in planned[0].state["evidence"]["excerpt"]
    assert planned[0].questions == EVIDENCE_SCREEN_QUESTIONS


def test_reference_batch_sends_full_text_once_and_binds_each_question():
    items = control_items()
    request = requests(items, objective="question", variant="batched_refs")[0]
    for key, (evidence_id, _) in request.bindings.items():
        assert request.questions[key]["instructions"]["evidence_id"] == evidence_id
        assert "evidence" not in request.questions[key]["instructions"]
    assert [row["excerpt"] for row in request.state["evidence"]] == [item.excerpt for item in items]


def test_full_payload_keeps_legal_source_and_analysis_after_short_excerpt():
    from tests.test_legal_research_result import _result

    legal = _result()
    legal.raw_text = legal.raw_text * 100
    item = replace(control_items()[0], legal_result=legal)
    request = requests([item], objective="question", variant="full")[0]
    assert request.state["evidence"][0]["legal_result"] == legal.model_dump(mode="json")
    assert request.state["evidence"][0]["legal_result"]["raw_text"] == legal.raw_text


async def test_mocked_batch_scores_are_bound_to_individual_evidence_ids():
    planned = requests(control_items(), objective="question", variant="batched")
    client = AsyncMock()
    client.ask.return_value = response(planned[0].questions)
    result = await measure(client, planned, model="fixed", concurrency=2, timeout_seconds=5)
    assert result["requests"] == 1 and result["evidence_count"] == 2
    assert set(result["scores"]) == {"control-0", "control-1"}
    assert result["calls"][0]["question_count"] == 12
    client.ask.assert_awaited_once()


@pytest.mark.parametrize("failure", ["transport", "missing", "nan"])
async def test_errors_propagate_without_partial_success_or_substitute(failure):
    planned = requests(control_items(), objective="question", variant="batched")
    client = AsyncMock()
    if failure == "transport":
        client.ask.side_effect = JevClientError("Unavailable", category="transport")
    else:
        client.ask.return_value = response(
            {} if failure == "missing" else planned[0].questions,
            value=float("nan") if failure == "nan" else 0.8,
        )
    with pytest.raises((JevClientError, ValueError)):
        await measure(client, planned, model="fixed", concurrency=2, timeout_seconds=5)
    client.ask.assert_awaited_once()


async def test_changed_resolved_model_invalidates_comparison():
    planned = requests(control_items(), objective="question", variant="full")
    client = AsyncMock()
    client.ask.side_effect = [response(planned[0].questions), response(planned[1].questions, model="other")]
    with pytest.raises(ValueError, match="model changed"):
        await measure(client, planned, model="fixed", concurrency=1, timeout_seconds=5)


def test_duplicate_ids_cannot_silently_overwrite_measurements():
    items = control_items()
    with pytest.raises(ValueError, match="unique"):
        requests([items[0], replace(items[1], evidence_id=items[0].evidence_id)], objective="q", variant="full")


async def test_failure_cancels_pending_calls_and_records_failure_category():
    planned = requests(control_items(), objective="question", variant="full")
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def external(**kwargs):
        if kwargs["state"]["evidence"][0]["evidence_id"] == "control-0":
            await entered.wait()
            raise JevClientError("HTTP 429", category="rate_limit")
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    journal = []
    with pytest.raises(JevClientError, match="429"):
        await measure(AsyncMock(ask=AsyncMock(side_effect=external)), planned,
            model="fixed", concurrency=2, timeout_seconds=5, journal=journal)
    assert cancelled.is_set()
    assert journal[0]["status"] == "error"
    assert journal[0]["error_category"] == "rate_limit"
    assert journal[1]["status"] == "cancelled"

import json
from dataclasses import replace
from hashlib import sha256
from unittest.mock import AsyncMock

import pytest

from tests.research_reuse.jev_windows import aggregate, contradiction_requests, plan, split
from tests.research_reuse.test_jev_passages import control_items, response

pytestmark = pytest.mark.research_reuse


@pytest.mark.parametrize("text", ["", "Åäö\r\n\t" * 500, "a" * 2401, "  text  \n"])
def test_windows_reconstruct_exact_text_and_sha_without_normalization(text):
    item = replace(control_items()[0], excerpt=text)
    passages = split(item, field="excerpt")
    assert "".join(p.text for p in passages) == text
    assert all(p.row["source_text_sha256"] == sha256(text.encode()).hexdigest() for p in passages)
    assert all(p.row["content_hash"] == item.content_hash for p in passages)
    assert all(p.row["excerpt"] == text[p.context_start:p.context_end] for p in passages)
    assert passages[0].start == 0 and passages[-1].end == len(text)
    assert all(a.end == b.start for a, b in zip(passages, passages[1:]))


def test_batch_budget_and_all_passage_bindings_are_preserved():
    items = control_items()
    batches, passages = plan(items, objective="q", field="excerpt", max_state_chars=6000)
    assert all(len(json.dumps(b.state, ensure_ascii=False)) <= 6000 for b in batches)
    assert all(len(b.questions) <= 16 for b in batches)
    assert {binding[0] for b in batches for binding in b.bindings.values()} == {p.id for p in passages}
    assert sum(len(b.questions) for b in batches) == len(passages) * 2
    for b in batches:
        for key, (passage_id, _) in b.bindings.items():
            assert b.questions[key]["instructions"]["passage_id"] == passage_id


def test_too_small_budget_fails_instead_of_clipping_or_skipping():
    with pytest.raises(ValueError, match="budget"):
        plan(control_items(), objective="q", field="excerpt", max_state_chars=100)


def test_source_variant_keeps_complete_raw_source_and_declares_its_field():
    from tests.test_legal_research_result import _result

    legal = _result()
    legal.raw_text *= 100
    item = replace(control_items()[0], legal_result=legal)
    passages = split(item, field="source")
    assert "".join(p.text for p in passages) == legal.raw_text
    assert all(p.field == "legal_result.raw_text" for p in passages)


def test_aggregation_cannot_mix_relevance_and_support_from_different_passages():
    passages = split(replace(control_items()[0], excerpt="a" * 2400), field="excerpt")
    scores = {passages[0].id: {"relevant_to_question": 0.99, "directly_supports_answer": 0.01},
        passages[1].id: {"relevant_to_question": 0.01, "directly_supports_answer": 0.99}}
    result = aggregate(scores, passages)[passages[0].evidence_id]
    assert result in list(scores.values())
    assert not (result["relevant_to_question"] >= .8 and result["directly_supports_answer"] >= .5)
    with pytest.raises(ValueError, match="missing"):
        aggregate({}, passages)


def test_contradiction_control_compares_both_complete_facts_in_both_directions():
    items = control_items()
    batches = contradiction_requests(items, "q")
    assert len(batches) == 2
    for i, b in enumerate(batches):
        assert b.state["evidence"]["excerpt"] == items[i].excerpt
        assert b.state["other_supplied_facts"][0]["excerpt"] == items[1 - i].excerpt
        assert len(b.questions) == 1


async def test_live_window_runner_records_full_coverage_with_mocked_service():
    from tests.research_reuse.jev_window_live import variant

    async def external(**kwargs):
        return response(kwargs["questions"])

    client = AsyncMock(ask=AsyncMock(side_effect=external))
    case = {"runs": [], "question": "q", "model": "fixed", "concurrency": 1, "state_budget": 6000}
    await variant(client, control_items(), case, "excerpt_windows")
    row = case["runs"][0]
    assert row["status"] == "completed" and row["evidence_count"] == 2
    assert row["covered_chars"] == sum(len(i.excerpt) for i in control_items())
    assert row["passage_count"] == len(row["coverage"])


async def test_pair_budget_failure_prevents_external_calls_without_clipping():
    from tests.research_reuse.jev_window_live import pair_control

    client = AsyncMock()
    case = {"runs": [], "question": "q", "model": "fixed", "concurrency": 1, "state_budget": 100}
    with pytest.raises(ValueError, match="budget"):
        await pair_control(client, control_items(), case)
    client.ask.assert_not_awaited()


async def test_diagnostics_preserve_http_error_and_redact_the_key(monkeypatch):
    import httpx
    from app.jev.system import HttpJevSystemOne
    from tests.research_reuse.jev_diagnostics import DiagnosticJev

    original = AsyncMock(return_value=httpx.Response(429, text="limit exceeded: secret-key",
        headers={"Retry-After": "12", "Authorization": "secret-key"}))
    monkeypatch.setattr(HttpJevSystemOne, "_post", original)
    client = DiagnosticJev()
    response = await client._post({}, "secret-key", 5)
    assert response.status_code == 429
    assert client.errors == [{"status": 429, "message": "limit exceeded: [redacted]",
        "limit_headers": {"retry-after": "12"}}]
    original.assert_awaited_once()

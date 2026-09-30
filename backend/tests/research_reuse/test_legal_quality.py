import asyncio
import hashlib
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.llm.legal_research import LlmLegalInterpreter
from app.services.legal_research_result import LegalResearchResult
from tests.research_reuse.helpers import context
from tests.research_reuse.legal_live import interpret_case
from tests.research_reuse.legal_quality import LegalBenchmarkInput, check_legal_quality

pytestmark = pytest.mark.research_reuse


def case():
    source_text = "Majoriteten beviljar jämkning.\n\nSkiljaktig mening: jämkning avslås."
    return LegalBenchmarkInput(
        id="majority_vs_dissent_control",
        source={
            "kind": "case_law",
            "title": "Synthetic control",
            "canonical_uri": "https://example.test/case",
        },
        question="Beviljade den avgörande domstolen jämkning?",
        raw_text=source_text,
        raw_text_sha256=hashlib.sha256(source_text.encode()).hexdigest(),
        expected={
            "holding_established": True,
            "adjustment_granted": True,
            "court_level": "supreme",
            "decision_basis": "statutory_adjustment",
            "forbidden_holding_spans": ["s1"],
        },
    )


def result(*, dissent=False):
    sample = case()
    citation = {
        "source_uri": sample.source.canonical_uri,
        "source_span_id": "s1" if dissent else "s0",
        "quote": sample.raw_text.split("\n\n")[1 if dissent else 0],
    }
    return LegalResearchResult.model_validate(
        {
            "source": sample.source.model_dump(),
            "raw_text": sample.raw_text,
            "relation": {"relation": "supports", "explanation": "Control", "confidence": "high"},
            "case_law": {
                "legal_issue": "Control",
                "court_reasoning": "Control",
                "citations": [citation],
                "authoritative_holding": {
                    "court_level": "supreme",
                    "text_role": "majority_reasons",
                    "outcome": citation["quote"],
                    "decision_basis": "statutory_adjustment",
                    "adjustment_granted": not dissent,
                    "citations": [citation],
                },
            },
        }
    )


def test_grounded_schema_valid_dissent_cannot_pass_as_majority():
    wrong = result(dissent=True)
    checks = check_legal_quality(wrong, case())
    assert not checks["adjustment_granted"]
    assert not checks["no_forbidden_holding_spans"]
    assert all(check_legal_quality(result(), case()).values())


def test_expected_holding_is_bound_to_exact_source():
    data = case().model_dump()
    data["raw_text"] += " changed"
    with pytest.raises(ValueError, match="exact source"):
        LegalBenchmarkInput.model_validate(data)


def test_summary_cannot_invent_holding():
    sample = case().model_copy(
        update={
            "expected": case().expected.model_copy(
                update={
                    "holding_established": False,
                    "adjustment_granted": None,
                    "court_level": None,
                    "decision_basis": None,
                }
            )
        }
    )
    checks = check_legal_quality(result(), sample)
    assert not checks["holding_established"]
    assert not checks["adjustment_granted"]


async def test_lab_rejects_valid_but_incorrect_interpretation_and_keeps_result():
    interpreter = AsyncMock()
    interpreter.interpret.return_value = result(dissent=True)
    row = await interpret_case(interpreter, case(), context())
    assert row["status"] == "success" and not row["passed"]
    assert row["result"]["case_law"]["authoritative_holding"]["adjustment_granted"] is False
    assert row["seconds"] >= 0


async def test_lab_reports_model_failure_without_using_a_substitute():
    from app.llm.legal_research import LegalDomainExtractionError

    interpreter = AsyncMock()
    interpreter.interpret.side_effect = LegalDomainExtractionError("Provider timed out")
    row = await interpret_case(interpreter, case(), context())
    assert row["status"] == "error" and not row["passed"]
    assert row["error_type"] == "LegalDomainExtractionError"
    interpreter.interpret.assert_awaited_once()


@pytest.mark.parametrize("outcome", ["error", "cancel"])
async def test_native_interpreter_releases_pool_before_external_call(
    reuse_db, monkeypatch, outcome
):
    async def prompts(session, **kwargs):
        await session.execute(text("SELECT 1"))
        return {"research.lagen_nu.domain.v3.court_passage": "Mock prompt"}

    monkeypatch.setattr("app.llm.legal_research.require_active_prompts", prompts)
    entered, release = asyncio.Event(), asyncio.Event()

    async def complete(*args, **kwargs):
        entered.set()
        await release.wait()
        raise RuntimeError("External service failed")

    native = LlmLegalInterpreter(completer=complete, session_factory=reuse_db)
    task = asyncio.create_task(interpret_case(native, case(), context()))
    await asyncio.wait_for(entered.wait(), 1)
    async with reuse_db() as session:
        assert await session.scalar(text("SELECT 1")) == 1
    if outcome == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        release.set()
        assert (await task)["status"] == "error"

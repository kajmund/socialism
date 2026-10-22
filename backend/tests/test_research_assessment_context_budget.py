"""Assessment input must fit the model context and mark omitted evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.llm.research_assessment import (
    EvidenceSufficiencyModel,
    LlmResearchAssessor,
    NeedSufficiencyModel,
)
from app.services.research.assessment import AssessableEvidence, ResearchAssessmentError
from app.services.research.assessment_input import (
    ASSESSMENT_MAX_INPUT_CHARS,
    encode_assessment_input,
)
from app.services.research.models import ResearchNeed, ResearchPlan

_LARGE_EXCERPT = "36 § avtalslagen " * 1_000


def _rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(33):
        found = index < 17
        rows.append(
            {
                "evidence_id": f"evidence-{index}",
                "research_need_id": f"need-{index}",
                "status": "found" if found else "not_found",
                "excerpt": f"unikt-{index} " + _LARGE_EXCERPT,
                "source_id": f"source-{index}",
                "title": f"title-{index}",
                "provenance": {},
                "legal_result": None,
            }
        )
    return rows


def _assessable(index: int) -> AssessableEvidence:
    return AssessableEvidence(
        evidence_id=f"evidence-{index}",
        research_need_id="research_1",
        source_type="case_knowledge",
        status="found" if index < 17 else "not_found",
        title=f"title-{index}",
        excerpt=f"unikt-{index} " + _LARGE_EXCERPT,
        locator=None,
        source_id=f"source-{index}",
        source_url=None,
        provider="fake",
        score=1.0,
        provenance={},
        retrieved_at=datetime(2026, 4, 1, tzinfo=UTC),
        content_hash=f"hash-{index}",
    )


def test_budget_keeps_found_evidence_and_marks_omissions() -> None:
    encoded = encode_assessment_input(_rows(), max_chars=40_000)
    encoded_size = len(
        json.dumps(encoded.payload, ensure_ascii=False, separators=(",", ":"))
    )

    assert encoded_size <= 40_000
    omitted = encoded.payload["omitted_evidence"]
    assert isinstance(omitted, list)
    assert omitted
    omitted_ids = {row["evidence_id"] for row in omitted}
    assert omitted_ids == set(encoded.omitted_evidence_ids)
    assert len(encoded.evidence_ids) + len(omitted_ids) == 33
    assert not any(
        str(row["evidence_id"]).startswith("evidence-")
        and int(str(row["evidence_id"]).split("-")[1]) < 17
        for row in omitted
    )
    assert encoded.payload["budget"]["omitted_evidence"] == len(omitted)


def test_budget_that_cannot_fit_even_one_item_fails_loudly() -> None:
    with pytest.raises(ResearchAssessmentError, match="does not fit"):
        encode_assessment_input(_rows(), max_chars=20)


@pytest.mark.asyncio
async def test_llm_assessor_truncates_large_evidence_instead_of_context_error() -> None:
    plan = ResearchPlan(
        needs=[
            ResearchNeed(
                id="research_1",
                question="Vilka avgöranden har tillämpat 36 § avtalslagen?",
                why_needed="assessment budget test",
                source_types=["case_knowledge"],
            )
        ]
    )
    observed: dict[str, int] = {}

    async def completer(messages, response_model):
        assert response_model is EvidenceSufficiencyModel
        chars = sum(len(message["content"]) for message in messages)
        observed["input_chars"] = chars
        # This is stricter than the real context error: the old unbounded
        # prompt is ~13x over the deterministic budget.
        if chars > ASSESSMENT_MAX_INPUT_CHARS + 20_000:
            raise RuntimeError("context_length_exceeded")
        return EvidenceSufficiencyModel(
            result="sufficient",
            rationale="budgeted input",
            need_assessments=[
                NeedSufficiencyModel(
                    research_need_id="research_1",
                    sufficient=True,
                    supporting_evidence_ids=["e0"],
                )
            ],
            considered_evidence_ids=["e0"],
        )

    assessor = LlmResearchAssessor(
        completer=completer,
        system_prompt="bedöm evidens",
        user_prompt="ResearchPlan:\n{plan_json}\n\nEvidenceSet:\n{evidence_json}",
    )
    draft = await assessor.assess(plan, [_assessable(index) for index in range(33)])

    assert draft.result == "sufficient"
    assert observed["input_chars"] <= ASSESSMENT_MAX_INPUT_CHARS + 20_000

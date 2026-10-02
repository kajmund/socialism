"""Compact assessment inputs preserve all selected support and canonical citations."""

import copy
import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.llm.research_assessment import (
    EvidenceSufficiencyModel,
    LlmResearchAssessor,
    NeedSufficiencyModel,
    _evidence_payload,
)
from app.services.research.assessment import group_evidence_for_review
from app.services.research.assessment_input import compact_provenance, encode_assessment_input
from app.services.research.reuse_gate import (
    assessable_candidates,
    assess_reuse,
    answer_is_sufficient,
)
from tests.research_reuse.helpers import evidence, need, restore_legal_input

pytestmark = pytest.mark.research_reuse


def encoded(items):
    return encode_assessment_input(
        [
            _evidence_payload(group)
            for group in group_evidence_for_review(assessable_candidates(items))
        ]
    )


def reconstruct(payload, row):
    return "".join(payload["passages"][ref] for ref in row["passage_ids"])


@pytest.mark.parametrize(
    "tail",
    [
        "Stödet står efter tvåtusen tecken.",
        "Undantaget gäller inte konsumentavtal.",
        "Det tidigare förslaget avvisades; slutsatsen är den motsatta.",
    ],
)
def test_long_source_keeps_late_support_exceptions_and_counterevidence(tail):
    original = replace(evidence(), excerpt="Bakgrund. " * 400 + "\n\n" + tail)
    payload = encoded([original]).payload
    assert reconstruct(payload, payload["evidence"][0]) == original.excerpt
    assert tail in json.dumps(payload, ensure_ascii=False)


def test_exact_shared_paragraphs_preserve_sources_order_repetitions_and_original_hashes():
    shared = "Gemensamt stycke.\n\n"
    first = replace(evidence(source_id="A"), excerpt=shared + shared + "Första slutsatsen.")
    second = replace(evidence(source_id="B"), excerpt=shared + "Andra slutsatsen.")
    inputs = assessable_candidates([first, second])
    before = copy.deepcopy(inputs)
    review = encode_assessment_input(
        [_evidence_payload(group) for group in group_evidence_for_review(inputs)]
    )
    rows = review.payload["evidence"]
    assert [reconstruct(review.payload, row) for row in rows] == [first.excerpt, second.excerpt]
    assert rows[0]["passage_ids"][:2] == rows[0]["passage_ids"][2:4] == rows[1]["passage_ids"][:2]
    assert rows[0]["source_id"] != rows[1]["source_id"]
    assert list(review.payload["passages"].values()).count(shared.rstrip("\n")) == 1
    assert inputs == before
    assert review.evidence_ids == {"e0": first.evidence_id, "e1": second.evidence_id}


@pytest.mark.parametrize("source", ["", "  ", "å\n\n", "a\n \n\nβ", "e\u0301\r\n\r\né\t"])
def test_passage_sharing_is_byte_exact_for_unicode_and_whitespace(source):
    payload = encoded([replace(evidence(), excerpt=source)]).payload
    restored = reconstruct(payload, payload["evidence"][0])
    assert restored.encode("utf-8") == source.encode("utf-8")


def test_same_source_is_recognizable_without_opaque_identifiers_or_review_status():
    base = replace(
        evidence(),
        metadata={
            "graph_fact_ids": ["opaque-id"] * 50,
            "supporting_text_unit_ids": ["opaque-unit"] * 50,
            "previous_answer_status": "sufficient",
            "answer_fact_id": "opaque-answer",
            "graph_fact_text": "Utsaga att kontrollera.",
            "primary_source": False,
            "derived": True,
            "not_official_publication": True,
            "source_date": "2020-01-01",
            "truncated": True,
            "passage_interpreter_clipped": True,
            "new_semantic_warning": "Uppgiften är omtvistad",
            "invalidated_at": "2025-01-01",
            "reuse": {
                "freshness": "fresh",
                "evidence_ref": "opaque-reference",
                "expires_at": "2026-01-01",
            },
        },
    )
    review = encoded([base, replace(base, excerpt="Ett annat stycke.")])
    rows = review.payload["evidence"]
    assert rows[0]["source_id"] == rows[1]["source_id"]
    assert "opaque" not in json.dumps(review.payload)
    assert "previous_answer_status" not in json.dumps(review.payload)
    assert rows[0]["provenance"] == compact_provenance(base.metadata)
    for flag in ("truncated", "passage_interpreter_clipped", "derived", "not_official_publication"):
        assert rows[0]["provenance"][flag] is True
    assert rows[0]["provenance"]["primary_source"] is False
    assert rows[0]["provenance"]["new_semantic_warning"] == "Uppgiften är omtvistad"
    assert rows[0]["provenance"]["invalidated_at"] == "2025-01-01"
    assert rows[0]["provenance"]["reuse"]["expires_at"] == "2026-01-01"


def test_legal_claims_quotes_quality_warnings_and_temporal_signals_survive_encoding():
    from app.services.research.quality import EvidenceQualityDraft, QualityFlag
    from tests.test_legal_research_result import _result

    legal = _result()
    item = replace(
        assessable_candidates([evidence()])[0],
        legal_result=legal,
        claims=(
            {
                "predicate": "legal.rule",
                "value": "Fordran preskriberas",
                "citations": [
                    {"source_uri": legal.source.canonical_uri, "quote": "fordran preskriberas"}
                ],
            },
        ),
        provenance={
            "valid_from": "2020-01-01",
            "valid_to": "2025-01-01",
            "observed_at": "2024-01-01",
            "authority_warning": "Verifiera originalet",
        },
        quality=EvidenceQualityDraft(
            evidence_set_item_id="item",
            original_evidence_id="original",
            scoring_policy_version="v1",
            authority="limited",
            relevance="high",
            currentness="unknown",
            source_nature="secondary",
            source_timestamp=None,
            independence_key="underlying-source",
            independent_source_count=1,
            flags=[QualityFlag("authority_warning", "Verifiera originalet")],
        ),
    )
    original = _evidence_payload(group_evidence_for_review([item])[0])
    payload = encode_assessment_input([original]).payload
    packed = payload["evidence"][0]
    restored = restore_legal_input(packed["legal_result"], payload)
    assert restored == original["legal_result"]
    for key in ("claims", "claim_citations", "quality", "provenance"):
        assert packed[key] == original[key]
    assert restored["statute"]["citations"][0]["quote"] == "fordran preskriberas"
    assert "raw_text" not in restored


async def test_a_valid_alias_for_another_question_cannot_supply_its_support():
    from app.services.research.models import ResearchPlan

    adapter = LlmResearchAssessor(
        completer=AsyncMock(
            return_value=EvidenceSufficiencyModel(
                result="sufficient",
                rationale="Crossed citations",
                need_assessments=[
                    NeedSufficiencyModel(
                        research_need_id="first",
                        sufficient=True,
                        supporting_evidence_ids=["e1"],
                    ),
                    NeedSufficiencyModel(
                        research_need_id="second",
                        sufficient=True,
                        supporting_evidence_ids=["e0"],
                    ),
                ],
                considered_evidence_ids=["e0", "e1"],
            )
        ),
        system_prompt="Mock boundary",
        user_prompt="{evidence_json}",
    )
    items = [evidence(need_id="first", source_id="A"), evidence(need_id="second", source_id="B")]
    result = await adapter.assess(
        ResearchPlan(needs=[need(need_id="first"), need(need_id="second")]),
        assessable_candidates(items),
    )
    assert result.result == "insufficient"
    assert all(
        not row.sufficient and not row.supporting_evidence_ids for row in result.need_assessments
    )
    assert set(result.considered_evidence_ids) == {item.evidence_id for item in items}


@pytest.mark.parametrize("citation", ["e0", "e99", "p0", "canonical", "other-request"])
async def test_model_citations_are_restored_only_from_this_requests_aliases(
    reuse_db,
    citation,
):
    item = replace(evidence(), evidence_id="canonical", excerpt="Belagt svar.")

    async def complete(messages, _response_model):
        payload = json.loads(messages[1]["content"])
        assert payload["evidence"][0]["evidence_id"] == "e0"
        assert "canonical" not in messages[1]["content"]
        async with reuse_db() as other:
            assert await other.scalar(text("SELECT 1")) == 1
        return EvidenceSufficiencyModel(
            result="sufficient",
            rationale="Bedömt",
            need_assessments=[
                NeedSufficiencyModel(
                    research_need_id="child",
                    sufficient=True,
                    supporting_evidence_ids=[citation],
                )
            ],
        )

    adapter = LlmResearchAssessor(
        completer=complete,
        system_prompt="Mock boundary",
        user_prompt="{evidence_json}",
    )
    result = await assess_reuse(adapter, need(), [item])
    assert answer_is_sufficient(result) is (citation == "e0")
    assert result.need_assessments[0].supporting_evidence_ids == (
        ["canonical"] if citation == "e0" else []
    )


async def test_an_omitted_question_still_fails_closed():
    adapter = LlmResearchAssessor(
        completer=AsyncMock(
            return_value=EvidenceSufficiencyModel(
                result="sufficient",
                rationale="Question omitted",
            )
        ),
        system_prompt="Mock boundary",
        user_prompt="{evidence_json}",
    )
    result = await assess_reuse(adapter, need(), [evidence()])
    assert not answer_is_sufficient(result)
    assert result.need_assessments[0].missing_or_weak == "Assessor omitted this ResearchNeed."


@pytest.mark.parametrize("global_conflict", [True, False])
async def test_valid_aliases_cannot_override_a_reported_factual_contradiction(global_conflict):
    conflict = ["Två gällande beslut anger olika datum"]
    adapter = LlmResearchAssessor(
        completer=AsyncMock(
            return_value=EvidenceSufficiencyModel(
                result="sufficient",
                rationale="Inconsistent model judgment",
                contradictions=conflict if global_conflict else [],
                need_assessments=[
                    NeedSufficiencyModel(
                        research_need_id="child",
                        sufficient=True,
                        supporting_evidence_ids=["e0"],
                        contradictions=[] if global_conflict else conflict,
                    )
                ],
            )
        ),
        system_prompt="Mock boundary",
        user_prompt="{evidence_json}",
    )
    item = evidence()
    result = await assess_reuse(adapter, need(), [item])
    assert result.need_assessments[0].supporting_evidence_ids == [item.evidence_id]
    assert not answer_is_sufficient(result)


@pytest.mark.parametrize("module", ["dd", "politik", "expertgranskning"])
async def test_assessment_format_instructions_are_seeded_in_an_empty_database(reuse_db, module):
    from app.services.prompt_defaults import prompt_defaults_for_module
    from app.services.prompt_fields_store import (
        ensure_prompt_field_defaults,
        get_prompt_field_by_key,
    )

    async with reuse_db() as session:
        await ensure_prompt_field_defaults(session, module, prompt_defaults_for_module(module))
        field = await get_prompt_field_by_key(session, "research.assessment.system")
        assert field is not None
        assert module in field.modules
        for system in (field.default_sv, field.default_en):
            assert "passage_ids" in system and "source_id" in system
            assert "legal_schemas" in system and "schema_id" in system

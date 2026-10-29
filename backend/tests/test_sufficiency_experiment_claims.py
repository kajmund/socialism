"""A3 claim candidates: deterministic segmentation, exact offsets, budgets."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from app.services.research.assessment import AssessableEvidence
from app.services.research.sufficiency_experiment.assessor import run_experiment
from app.services.research.sufficiency_experiment.claims import extract_claim_candidates
from app.services.research.sufficiency_experiment.golden import short_sufficient
from app.services.research.sufficiency_experiment.scripted import ScriptedSufficiencyJev
from app.services.research.sufficiency_experiment.types import (
    EvidencePassage,
    ExperimentConfig,
)


def _evidence(
    evidence_id: str = "ev-1",
    *,
    provenance: dict[str, object] | None = None,
) -> AssessableEvidence:
    return AssessableEvidence(
        evidence_id=evidence_id,
        research_need_id="research_1",
        source_type="case_knowledge",
        status="found",
        title=evidence_id,
        excerpt="text",
        locator=None,
        source_id=f"source-{evidence_id}",
        source_url=None,
        provider="fixture",
        score=1.0,
        provenance=provenance or {},
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_hash=f"hash-{evidence_id}",
    )


def _passage(
    text: str,
    *,
    evidence_id: str = "ev-1",
    need_ids: tuple[str, ...] = ("research_1",),
) -> EvidencePassage:
    return EvidencePassage(
        passage_id=f"{evidence_id}:p0",
        evidence_id=evidence_id,
        research_need_ids=need_ids,
        start=0,
        end=len(text),
        text=text,
        content_hash=f"hash-{evidence_id}",
        source_chars=len(text),
    )


def _extract(
    passages: list[EvidencePassage],
    evidence: list[AssessableEvidence],
    *,
    config: ExperimentConfig | None = None,
):
    return extract_claim_candidates(
        passages,
        {item.evidence_id: item for item in evidence},
        config=config or ExperimentConfig(),
    )


def test_offsets_preserve_the_exact_passage_text() -> None:
    passage = _passage(
        "Första påståendet är att avtalet gäller. Andra påståendet är att det upphör."
    )
    candidates, _ = _extract([passage], [_evidence()])
    for candidate in candidates:
        assert passage.text[candidate.start : candidate.end] == candidate.text
        assert candidate.text.strip() == candidate.text


def test_multiclause_sentence_stays_one_candidate() -> None:
    text = (
        "Avtalet förlängs automatiskt med tolv månader om ingen part säger upp "
        "det senast tre månader före avtalstidens slut."
    )
    candidates, coverage = _extract([_passage(text)], [_evidence()])
    assert len(candidates) == 1
    assert coverage.extracted == 1
    assert candidates[0].text == text


def test_uncertain_candidates_are_visible_with_a_reason() -> None:
    text = (
        "Vilka avgöranden har tillämpat 36 § avtalslagen i praktiken? "
        "Inledning. "
        "Högsta domstolens avgörande NJA 2005 s. 142."
    )
    candidates, coverage = _extract([_passage(text)], [_evidence()])
    reasons = {candidate.uncertain_reason for candidate in candidates}
    assert "question" in reasons
    assert "too_short" in reasons
    assert "citation_only" in reasons
    assert coverage.uncertain == 3
    assert coverage.extracted == 0


def test_quoted_decisive_claim_is_not_a_pure_citation() -> None:
    text = '"Domstolen fann att villkoret var oskäligt och jämkade det."'
    candidates, coverage = _extract([_passage(text)], [_evidence()])
    assert coverage.extracted == 1
    assert candidates[0].text == text


def test_too_long_candidate_is_uncertain() -> None:
    config = replace(ExperimentConfig(), max_claim_chars=40)
    text = "Detta är en lång mening som överstiger budgeten för en claim."
    candidates, _ = _extract([_passage(text)], [_evidence()], config=config)
    assert candidates[0].extraction_status == "uncertain"
    assert candidates[0].uncertain_reason == "too_long"


def test_metadata_is_copied_only_from_provenance() -> None:
    provenance = {
        "entity_id": "avtal-1",
        "valid_from": "2024-01-01",
        "valid_to": "2024-12-31",
        "definition_id": "uppsagningstid",
    }
    text = "Uppsägningstiden är tre månader för avtalet."
    candidates, _ = _extract(
        [_passage(text)], [_evidence(provenance=provenance)]
    )
    candidate = candidates[0]
    assert candidate.entity_id == "avtal-1"
    assert candidate.valid_from == "2024-01-01"
    assert candidate.definition_id == "uppsagningstid"
    missing, _ = _extract([_passage(text)], [_evidence()])
    assert missing[0].entity_id is None
    assert missing[0].valid_from is None


def test_canonical_key_groups_but_occurrences_stay_separate() -> None:
    text = "Uppsägningstiden är tre månader för avtalet."
    passages = [_passage(text, evidence_id="ev-1"), _passage(text, evidence_id="ev-2")]
    candidates, _ = _extract(passages, [_evidence("ev-1"), _evidence("ev-2")])
    assert candidates[0].canonical_key == candidates[1].canonical_key
    assert candidates[0].claim_id != candidates[1].claim_id
    assert candidates[0].evidence_id != candidates[1].evidence_id


def test_budget_caps_mark_unprocessed_and_incomplete_coverage() -> None:
    config = replace(
        ExperimentConfig(),
        max_claims_per_need=2,
        min_claim_chars=5,
        min_claim_words=2,
    )
    text = (
        "Påstående ett. Påstående två. Påstående tre. "
        "Påstående fyra. Påstående fem."
    )
    candidates, coverage = _extract([_passage(text)], [_evidence()], config=config)
    assert len(candidates) == 5
    assert coverage.extracted == 2
    assert coverage.unprocessed == 3
    assert coverage.complete is False
    assert coverage.reasons == ("claim_budget:research_1",)
    assert coverage.per_need == (("research_1", 2),)
    assert coverage.per_evidence == (("ev-1", 5),)


def test_extraction_is_deterministic() -> None:
    text = "Första påståendet. Andra påståendet. Tredje påståendet."
    left, left_coverage = _extract([_passage(text)], [_evidence()])
    right, right_coverage = _extract([_passage(text)], [_evidence()])
    assert left == right
    assert left_coverage == right_coverage


async def test_incomplete_claim_coverage_blocks_sufficient() -> None:
    case = short_sufficient()
    config = replace(ExperimentConfig(), max_claims_per_need=0)
    report = await run_experiment(
        case.plan,
        case.evidence,
        client=ScriptedSufficiencyJev(),
        config=config,
    )
    assert report.claim_coverage is not None
    assert report.claim_coverage.complete is False
    assert "claim_coverage_incomplete" in report.quality.reasons
    assert report.draft.result == "insufficient"


async def test_complete_claim_coverage_is_reported() -> None:
    case = short_sufficient()
    report = await run_experiment(
        case.plan, case.evidence, client=ScriptedSufficiencyJev()
    )
    assert report.claims
    assert report.claim_coverage is not None
    assert report.claim_coverage.complete is True
    assert report.claim_coverage.candidates == len(report.claims)
    assert report.draft.result == "sufficient"

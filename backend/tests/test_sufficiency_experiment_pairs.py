"""Candidate-pair strategies: recall before and after the pair budget."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.services.research.sufficiency_experiment.claims import (
    extract_claim_candidates,
)
from app.services.research.sufficiency_experiment.golden import all_golden_cases
from app.services.research.sufficiency_experiment.pairs import select_pairs
from app.services.research.sufficiency_experiment.segment import segment_evidence
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    PairSelection,
)

GOLD = Path(__file__).resolve().parent / "integration" / "baselines" / "pair-gold-v1.json"


class FakeEmbeddingProvider:
    provider_id = "fake"
    model = "fake-embeddings"
    dimension = 2

    def __init__(self) -> None:
        self.calls = 0
        self.texts = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.texts += len(texts)
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        lowered = text.lower()
        return [
            1.0 if "avtalslagen" in lowered else 0.01,
            1.0 if "uppsägning" in lowered else 0.01,
        ]


def _config() -> ExperimentConfig:
    return ExperimentConfig()


def _claims(case):
    passages = segment_evidence(case.evidence, max_chars=_config().max_passage_chars)
    return extract_claim_candidates(
        passages,
        {item.evidence_id: item for item in case.evidence},
        config=_config(),
    )[0]


def _case(case_id: str):
    return next(case for case in all_golden_cases() if case.case_id == case_id)


def _gold() -> dict:
    return json.loads(GOLD.read_text(encoding="utf-8"))


def _facit(entry: dict) -> set[str]:
    return {"|".join(sorted(pair)) for pair in entry["candidate_pairs"]}


def _recall(selection: PairSelection, facit: set[str]) -> tuple[float, float]:
    candidate_ids = {pair.pair_id for pair in selection.candidates}
    selected_ids = {pair.pair_id for pair in selection.selected}
    before = len(facit & candidate_ids) / len(facit)
    after = len(facit & selected_ids) / len(facit)
    return before, after


async def test_deterministic_recall_survives_the_budget() -> None:
    entries = [entry for entry in _gold()["cases"] if not entry["negative_control"]]
    for entry in entries:
        case = _case(entry["case_id"])
        selection = await select_pairs(
            _claims(case),
            case.plan.needs,
            strategy="deterministic",
            config=_config(),
        )
        before, after = _recall(selection, _facit(entry))
        assert before == 1.0, entry["case_id"]
        assert after == 1.0, entry["case_id"]
        assert selection.omitted_by_budget >= 0


async def test_canonical_key_does_not_exclude_a_pair() -> None:
    case = _case("compatible_entities")
    claims = list(_claims(case))
    left = replace(claims[0], canonical_key="shared")
    right = replace(claims[1], canonical_key="shared", entity_id="other")
    selection = await select_pairs(
        [left, right],
        case.plan.needs,
        strategy="deterministic",
        config=_config(),
    )
    ids = {pair.pair_id for pair in selection.candidates}
    assert "|".join(sorted((left.claim_id, right.claim_id))) in ids


async def test_budget_can_drop_a_pair_found_before_the_budget() -> None:
    entry = next(
        entry
        for entry in _gold()["cases"]
        if entry["case_id"] == "duplicate_contradiction"
    )
    case = _case("duplicate_contradiction")
    config = replace(_config(), max_pairs_per_need=0)
    selection = await select_pairs(
        _claims(case), case.plan.needs, strategy="deterministic", config=config
    )
    before, after = _recall(selection, _facit(entry))
    assert before == 1.0
    assert after == 0.0
    assert selection.selected == ()
    assert selection.omitted_by_budget == len(selection.candidates)


async def test_embeddings_require_a_provider() -> None:
    case = _case("duplicate_contradiction")
    with pytest.raises(ValueError, match="embedding provider"):
        await select_pairs(
            _claims(case),
            case.plan.needs,
            strategy="embeddings",
            config=_config(),
        )


async def test_embeddings_and_hybrid_with_a_fake_provider() -> None:
    case = _case("duplicate_contradiction")
    provider = FakeEmbeddingProvider()
    claims = _claims(case)
    embedded = await select_pairs(
        claims,
        case.plan.needs,
        strategy="embeddings",
        config=_config(),
        embedding_provider=provider,
    )
    assert embedded.embedding_calls == 1
    assert embedded.embedding_texts == len(claims)
    hybrid_provider = FakeEmbeddingProvider()
    hybrid = await select_pairs(
        claims,
        case.plan.needs,
        strategy="hybrid",
        config=_config(),
        embedding_provider=hybrid_provider,
    )
    facit = _facit(
        next(
            entry
            for entry in _gold()["cases"]
            if entry["case_id"] == "duplicate_contradiction"
        )
    )
    assert facit <= {pair.pair_id for pair in hybrid.selected}
    sources = {
        pair.pair_id: pair.sources
        for pair in hybrid.candidates
        if pair.pair_id in facit
    }
    assert set(next(iter(sources.values()))) == {"deterministic", "embeddings"}


async def test_facit_ids_resolve_and_negative_control_is_separate() -> None:
    gold = _gold()
    for entry in gold["cases"]:
        case = _case(entry["case_id"])
        claim_ids = {claim.claim_id for claim in _claims(case)}
        for pair in entry["candidate_pairs"]:
            assert set(pair) <= claim_ids
    negative = [entry for entry in gold["cases"] if entry["negative_control"]]
    assert [entry["case_id"] for entry in negative] == ["unknown_counterpart"]
    assert negative[0]["candidate_pairs"] == []


async def test_reversed_pair_order_gives_the_same_id() -> None:
    case = _case("compatible_periods")
    claims = _claims(case)
    forward = await select_pairs(
        claims, case.plan.needs, strategy="deterministic", config=_config()
    )
    backward = await select_pairs(
        list(reversed(claims)),
        case.plan.needs,
        strategy="deterministic",
        config=_config(),
    )
    assert [pair.pair_id for pair in forward.candidates] == [
        pair.pair_id for pair in backward.candidates
    ]

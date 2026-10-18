from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.jev.client import JevResult
from overgraph_ingest.jev.questions import parse_choice, parse_confidence
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_probability_baseline,
)
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.tabular.cells import VARIANT_B
from overgraph_ingest.tabular.contract import ANSWERED, NOT_FOUND
from overgraph_ingest.tabular.evaluate import FALSE_ANSWER, TRUE_ANSWER
from overgraph_ingest.tabular.gold import USER_QUESTIONS
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.probability import (
    P2_IMPLEMENTED,
    PROBABILITY_ID,
    SCORE_TYPE,
    analyze_scores,
    derive_status_from_score,
    freeze_tabular_probability,
    inventory_jev_scores,
    run_tabular_probability,
    write_tabular_probability_baseline,
)
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.search import DEFAULT_K
from tests.test_tabular_review import ScriptedJev, _unit

ROOT = Path(__file__).resolve().parents[1]
TABULAR_V1 = ROOT / "baselines" / "phase2-tabular-review-v1.json"
DIRECT = ROOT / "baselines" / "phase2-tabular-direct-v1.json"
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"
PATH = "Avtal_05_Konsultavtal.docx"
GOLD_TEXT = "Avtalet förlängs automatiskt med tolv månader."


class ConfidenceJev(ScriptedJev):
    def __init__(self, confidence: float = 0.91) -> None:
        super().__init__()
        self.confidence = confidence

    def ask(self, *, state, questions, model, timeout_seconds):
        result = super().ask(
            state=state,
            questions=questions,
            model=model,
            timeout_seconds=timeout_seconds,
        )
        answers = {
            key: {**row, "confidence": self.confidence}
            if isinstance(row, dict)
            else row
            for key, row in result.answers.items()
        }
        return JevResult(
            answers=answers,
            model=result.model,
            latency_ms=result.latency_ms,
            usage=result.usage,
            raw={"answers": answers},
        )


def _units() -> list:
    rows = [
        _unit(f"noise-{index}", PATH, "Ingen sekretess.", sequence=index)
        for index in range(1, 5)
    ]
    rows.append(_unit("gold", PATH, GOLD_TEXT, sequence=5))
    return rows


def _gold() -> RetrievalGold:
    return RetrievalGold(
        id="auto-renewal",
        query=USER_QUESTIONS["auto-renewal"],
        classify_question="Innehåller texten bestämmelsen?",
        relevant_units=[GoldSpan(PATH, "förlängs automatiskt")],
        hard_negatives=[],
    )


def _frozen_cell() -> dict[str, object]:
    keys = [f"noise-{index}" for index in range(1, 5)] + ["gold"]
    return {
        "document_id": "Avtal_05_Konsultavtal",
        "relative_path": PATH,
        "question_id": "auto-renewal",
        "question": USER_QUESTIONS["auto-renewal"],
        "variant": VARIANT_B,
        "status": NOT_FOUND,
        "retrieval": {"k": 5, "candidate_keys": keys, "recall@5": 1.0},
    }


def test_default_p0_and_k_stay() -> None:
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS
    assert DEFAULT_K == 5
    assert P2_IMPLEMENTED is False


def test_inventory_documents_existing_choice_confidence() -> None:
    inventory = inventory_jev_scores()
    assert inventory["score_field"] == "confidence"
    assert inventory["score_type"] == SCORE_TYPE
    assert inventory["returns_all_alternatives"] is True
    assert inventory["distribution_field"] == "probabilities"
    assert inventory["score_is_token_logprob"] is False
    assert inventory["score_is_legal_correctness"] is False
    assert inventory["answer_cell_can_read_without_extra_call"] is True
    assert inventory["tabular_baselines_contain_scores"] is False
    assert inventory["replay_possible"] is False
    assert inventory["p2_implemented"] is False
    assert inventory["classify_prior"]["confidence_is_not_calibrated_probability"] is True


def test_parse_confidence_reads_chosen_alternative_only() -> None:
    label, score = parse_choice({"u1": {"choice": "yes", "confidence": 0.8}}, "u1")
    assert label == "YES"
    assert score == 0.8
    assert parse_confidence({"choice": ANSWERED, "confidence": 0.4}, key="status") == 0.4
    assert parse_confidence({"choice": ANSWERED}, key="status") is None


def test_p2_is_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="P2 waits"):
        derive_status_from_score(0.91)


def test_score_does_not_change_status(tmp_path: Path) -> None:
    payload = run_tabular_probability(
        units=_units(),
        structures={},
        golds=[_gold()],
        jev=ConfidenceJev(0.91),
        expected_cells=1,
        frozen={"cells": [_frozen_cell()], "scored": []},
        write_table=False,
    )
    row = payload["observations"][0]
    assert payload["status_unchanged_by_score"] is True
    assert payload["p2_implemented"] is False
    assert payload["no_extra_model_call"] is True
    assert payload["default_prompt_unchanged"] is True
    assert row["model_decision"] == ANSWERED
    assert row["model_score"] == 0.91
    assert row["score_type"] == SCORE_TYPE
    assert row["outcome"] == TRUE_ANSWER
    assert payload["cells"][0]["status"] == ANSWERED


def test_analyze_overlapping_scores_keeps_explicit_uncertain() -> None:
    rows = [
        _obs(TRUE_ANSWER, ANSWERED, 0.93),
        _obs(FALSE_ANSWER, ANSWERED, 0.96),
    ]
    analysis = analyze_scores(rows)
    assert analysis["usable_separation"] is False
    assert analysis["score_ranges_overlap"] is True
    assert analysis["decision"]["verdict"] == "keep_explicit_uncertain"
    assert analysis["decision"]["implement_p2"] is False
    assert analysis["p2_implemented"] is False


def test_analyze_missing_scores_does_not_invent_them() -> None:
    analysis = analyze_scores([_obs(TRUE_ANSWER, ANSWERED, None)])
    assert analysis["decision"]["verdict"] == "no_score_exposed"


def test_freeze_does_not_overwrite_protected_baselines(tmp_path: Path) -> None:
    before_v1 = TABULAR_V1.read_bytes()
    before_direct = DIRECT.read_bytes()
    before_c8 = C8.read_bytes()
    payload = {
        "headline": {},
        "inventory": {},
        "analysis": {},
        "decision": {},
        "quality": {},
        "observations": [],
        "cells": [],
        "wall_seconds": 1.0,
    }
    target = tmp_path / "phase2-tabular-jev-probability-v1.json"
    write_tabular_probability_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_tabular_probability_baseline(payload, target)
    with pytest.raises(ValueError, match="must not overwrite"):
        write_tabular_probability_baseline(payload, C8)
    frozen = freeze_tabular_probability(payload)
    assert frozen["id"] == PROBABILITY_ID
    assert frozen["p2_implemented"] is False
    assert frozen["default_prompt_unchanged"] is True
    assert TABULAR_V1.read_bytes() == before_v1
    assert DIRECT.read_bytes() == before_direct
    assert C8.read_bytes() == before_c8
    assert RETRIEVAL_CONCLUSIONS["do_not_change_jev_prompt"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_probability_p2_implemented"] is False
    assert RETRIEVAL_CONCLUSIONS["tabular_probability_keep_explicit_uncertain"] is True


def test_frozen_probability_rejected_score_status() -> None:
    frozen = load_tabular_probability_baseline()
    assert frozen["id"] == PROBABILITY_ID
    assert frozen["p2_implemented"] is False
    assert frozen["default_prompt_unchanged"] is True
    assert frozen["analysis"]["usable_separation"] is False
    assert frozen["analysis"]["score_ranges_overlap"] is True
    assert frozen["decision"]["verdict"] == "keep_explicit_uncertain"
    assert frozen["headline"]["live_score_present"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_probability"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_probability_rejected"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_change_jev_prompt"] is True


def _obs(outcome: str, status: str, score: float | None) -> dict[str, object]:
    return {
        "question_id": "auto-renewal",
        "model_decision": status,
        "model_score": score,
        "outcome": outcome,
        "status": status,
        "full_success": outcome == TRUE_ANSWER,
        "answer_correct": outcome == TRUE_ANSWER,
        "citation_relevant": outcome == TRUE_ANSWER,
        "citation_grounded": True,
        "gold_positive": True,
        "recall@3": 1.0,
        "recall@5": 1.0,
        "recall@10": 1.0,
        "navigation_successes": 0,
        "navigation_failures": 0,
        "jev_calls": 1,
        "cerebras_calls": 0,
        "cell_seconds": 0.3,
        "retrieve_seconds": 0.0,
        "classify_seconds": 0.0,
        "navigate_seconds": 0.0,
        "answer_seconds": 0.3,
    }

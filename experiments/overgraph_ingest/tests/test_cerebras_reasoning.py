import json

import pytest

from overgraph_ingest.cerebras.client import CerebrasReply
from overgraph_ingest.cerebras.evaluate import score_negations
from overgraph_ingest.cerebras.prompt import MATCH, NO_MATCH, Candidate, ParsedJudgment
from overgraph_ingest.cerebras.qwen import freeze_cerebras_qwen
from overgraph_ingest.cerebras.reasoning import (
    LOWEST_SUPPORTED,
    REASONING_OFF_SUPPORTED,
    freeze_cerebras_reasoning,
    run_cerebras_reasoning,
)
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.jev.candidates import GraphContext
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_cerebras_qwen_baseline,
    load_cerebras_reasoning_baseline,
)
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.retrieval.index import StoredUnit


def _gold() -> RetrievalGold:
    return RetrievalGold(
        id="auto-renewal",
        query="Vilka avtal innehåller bestämmelser om automatisk förlängning?",
        relevant_units=[],
        hard_negatives=[GoldSpan("b.docx", "förlängs inte automatiskt")],
        watch_negatives=[],
        document_gold=("a.docx", "b.docx"),
    )


class _FakeCompleter:
    def complete(self, messages: list[dict[str, str]]) -> CerebrasReply:
        assert "Ingen motivering" in messages[1]["content"]
        return CerebrasReply(
            text='{"match":["c01"],"uncertain":[]}',
            ttft_seconds=0.05,
            completion_seconds=0.1,
            prompt_tokens=80,
            completion_tokens=12,
            reasoning_tokens=4,
        )


def test_qwen_is_rejected_for_naive_rerank() -> None:
    frozen = freeze_cerebras_qwen(
        {
            "quality_reference": QUALITY_REFERENCE,
            "k": 50,
            "model": "qwen-3.8-27b",
            "reference_model": "gpt-oss-120b",
            "summary": {"golds": 0},
            "golds": [],
        }
    )
    assert frozen["verdict"] == "rejected_for_naive_rerank"
    assert frozen["do_not_deploy"] is True
    assert frozen["best_naive_rerank"] == "phase2-cerebras-output-v1"
    assert RETRIEVAL_CONCLUSIONS["cerebras_qwen"] == "rejected_for_naive_rerank"
    assert RETRIEVAL_CONCLUSIONS["best_naive_rerank"] == "phase2-cerebras-output-v1"


def test_hard_negative_match_is_counted_separately() -> None:
    candidates = [
        Candidate("c01", "rel", "a.docx", 1, "förlängs automatiskt"),
        Candidate("c02", "neg", "b.docx", 2, "förlängs inte automatiskt"),
    ]
    scored = score_negations(
        candidates=candidates,
        judgments=[
            ParsedJudgment("c01", "rel", MATCH, ""),
            ParsedJudgment("c02", "neg", MATCH, ""),
        ],
        hard_keys={"neg"},
        watch_keys=set(),
    )
    assert scored["hard_negatives_in_candidates"] == 1
    assert scored["hard_negatives_matched"] == 1
    skipped = score_negations(
        candidates=candidates,
        judgments=[
            ParsedJudgment("c01", "rel", MATCH, ""),
            ParsedJudgment("c02", "neg", NO_MATCH, ""),
        ],
        hard_keys={"neg"},
        watch_keys=set(),
    )
    assert skipped["hard_negatives_matched"] == 0


def test_reasoning_off_is_unsupported() -> None:
    assert REASONING_OFF_SUPPORTED is False
    assert LOWEST_SUPPORTED == "low"
    assert RETRIEVAL_CONCLUSIONS["cerebras_reasoning_off_supported"] is False
    frozen = freeze_cerebras_reasoning(
        {
            "quality_reference": QUALITY_REFERENCE,
            "k": 50,
            "model": "gpt-oss-120b",
            "current_setting": "unset_default_medium",
            "lowest_supported": "low",
            "reasoning_off_supported": False,
            "summary": {},
            "variants": {},
        }
    )
    assert frozen["reasoning_off_supported"] is False
    assert frozen["current_was_not_rerun"] is True
    assert frozen["does_not_replace_cerebras_output"] is True


def test_reasoning_run_does_not_rerun_current(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen = tmp_path / "frozen.json"
    frozen.write_text(
        json.dumps(
            {
                "k": 2,
                "golds": [
                    {
                        "gold_id": "auto-renewal",
                        "judgments": [
                            {"id": "c01", "key": "k1"},
                            {"id": "c02", "key": "k2"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    current = tmp_path / "output-v1.json"
    current.write_text(
        json.dumps(
            {
                "golds": [
                    {
                        "gold_id": "auto-renewal",
                        "prompt_tokens": 200,
                        "judgments": [
                            {"id": "c01", "key": "k1", "label": MATCH},
                            {"id": "c02", "key": "k2", "label": NO_MATCH},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    units = [
        StoredUnit(1, "k1", "d1", "a.docx", "förlängs automatiskt", None, None),
        StoredUnit(2, "k2", "d2", "b.docx", "förlängs inte automatiskt", None, None),
    ]

    class _Db:
        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "overgraph_ingest.cerebras.reasoning.open_database",
        lambda *_args, **_kwargs: _Db(),
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.reasoning.resolve_dimension",
        lambda *_args, **_kwargs: 3072,
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.reasoning.load_graph_context",
        lambda *_args, **_kwargs: GraphContext(units, {}, {}, {}),
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.reasoning._golds",
        lambda *_args, **_kwargs: [_gold()],
    )
    payload = run_cerebras_reasoning(
        frozen_path=frozen,
        current_path=current,
        client=_FakeCompleter(),
    )
    assert payload["reasoning_off_supported"] is False
    assert payload["current_was_not_rerun"] is True
    current_row = payload["variants"]["unset_default_medium"]["golds"][0]
    low_row = payload["variants"]["low"]["golds"][0]
    assert current_row["hard_negatives_matched"] == 0
    assert low_row["completion_tokens"] == 12
    assert low_row["delta"]["candidate_recall"] == 0.0


def test_qwen_baseline_is_rejected() -> None:
    frozen = load_cerebras_qwen_baseline()
    assert frozen["verdict"] == "rejected_for_naive_rerank"
    assert frozen["best_naive_rerank"] == "phase2-cerebras-output-v1"


def test_cerebras_reasoning_baseline() -> None:
    frozen = load_cerebras_reasoning_baseline()
    assert frozen["reasoning_off_supported"] is False
    assert frozen["lowest_supported"] == "low"
    assert frozen["current_was_not_rerun"] is True
    assert frozen["headline"]["quality_reference"]["true_support"] == 24
    current = frozen["headline"]["variants"]["unset_default_medium"]["summary"]
    low = frozen["headline"]["variants"]["low"]["summary"]
    assert current["mean_candidate_recall"] == 1.0
    assert low["mean_candidate_recall"] < 1.0
    assert low["total_completion_tokens"] < current["total_completion_tokens"]
    assert current["total_hard_negatives_matched"] == 1
    assert low["total_hard_negatives_matched"] == 1
    golds = {row["gold_id"]: row for row in frozen["headline"]["variants"]["low"]["golds"]}
    assert golds["liability-cap"]["candidate_recall"] < 1.0
    assert golds["auto-renewal"]["candidate_recall"] == 1.0

import json

import pytest

from overgraph_ingest.cerebras.client import CerebrasReply
from overgraph_ingest.cerebras.pricing import cost_usd
from overgraph_ingest.cerebras.qwen import (
    QWEN_MAX_COMPLETION_TOKENS,
    QWEN_MODEL,
    QWEN_REASONING_EFFORT,
    freeze_cerebras_qwen,
    run_cerebras_qwen,
)
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.jev.candidates import GraphContext
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_cerebras_qwen_baseline,
)
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.index import StoredUnit


def _gold() -> RetrievalGold:
    return RetrievalGold(
        id="auto-renewal",
        query="Vilka avtal innehåller bestämmelser om automatisk förlängning?",
        relevant_units=[],
        hard_negatives=[],
        document_gold=("a.docx", "b.docx"),
    )


class _FakeCompleter:
    def complete(self, messages: list[dict[str, str]]) -> CerebrasReply:
        assert "Ingen motivering" in messages[1]["content"]
        return CerebrasReply(
            text='{"match":["c01"],"uncertain":[]}',
            ttft_seconds=0.1,
            completion_seconds=0.2,
            prompt_tokens=100,
            completion_tokens=8,
        )


def test_qwen_rate_card_cost() -> None:
    assert cost_usd("gpt-oss-120b", 1_000_000, 1_000_000) == 1.1
    assert cost_usd("qwen-3.8-27b", 1_000_000, 0) == 0.99
    with pytest.raises(ValueError, match="no published Cerebras rate"):
        cost_usd("unknown-model", 1, 1)


def test_qwen_freeze_does_not_replace_output() -> None:
    frozen = freeze_cerebras_qwen(
        {
            "quality_reference": QUALITY_REFERENCE,
            "k": 50,
            "model": QWEN_MODEL,
            "reference_model": "gpt-oss-120b",
            "summary": {"golds": 0},
            "golds": [],
        }
    )
    assert frozen["does_not_replace_cerebras_output"] is True
    assert frozen["does_not_replace_cerebras_rerank"] is True
    assert frozen["verdict"] == "rejected_for_naive_rerank"
    assert frozen["same_minimal_json"] is True
    assert frozen["same_frozen_top50"] is True


def test_qwen_run_uses_frozen_keys_and_minimal_json(
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
    reference = tmp_path / "output-v1.json"
    reference.write_text(
        json.dumps(
            {
                "headline": {
                    "summary": {
                        "total_prompt_tokens": 200,
                        "total_completion_tokens": 80,
                    },
                    "golds": [
                        {
                            "gold_id": "auto-renewal",
                            "precision": 1.0,
                            "candidate_recall": 1.0,
                            "completion_tokens": 80,
                            "ttft_seconds": 1.0,
                            "model_seconds": 2.0,
                            "match": 1,
                            "uncertain": 0,
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    units = [
        StoredUnit(1, "k1", "d1", "a.docx", "förlängs automatiskt", None, None),
        StoredUnit(2, "k2", "d2", "b.docx", "annat", None, None),
    ]

    class _Db:
        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "overgraph_ingest.cerebras.qwen.open_database", lambda *_args, **_kwargs: _Db()
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.qwen.resolve_dimension", lambda *_args, **_kwargs: 3072
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.qwen.load_graph_context",
        lambda *_args, **_kwargs: GraphContext(units, {}, {}, {}),
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.qwen._golds",
        lambda *_args, **_kwargs: [_gold()],
    )
    payload = run_cerebras_qwen(
        frozen_path=frozen,
        reference_path=reference,
        client=_FakeCompleter(),
    )
    assert payload["model"] == QWEN_MODEL
    assert payload["reasoning_effort"] == QWEN_REASONING_EFFORT
    assert payload["max_completion_tokens"] == QWEN_MAX_COMPLETION_TOKENS
    assert payload["default_reasoning_emits_no_json"] is True
    assert payload["same_frozen_top50"] is True
    assert payload["same_minimal_json"] is True
    assert payload["no_new_retrieval"] is True
    row = payload["golds"][0]
    assert row["retrieval_seconds"] == 0.0
    assert row["cost_usd"] == cost_usd(QWEN_MODEL, 100, 8)
    assert row["delta"]["completion_tokens"] == -72
    assert payload["summary"]["cost_usd"] == cost_usd(QWEN_MODEL, 100, 8)
    assert payload["summary"]["reference_cost_usd"] == cost_usd("gpt-oss-120b", 200, 80)
    assert RETRIEVAL_CONCLUSIONS["cerebras_qwen_does_not_replace_c8"] is True


def test_cerebras_qwen_baseline() -> None:
    frozen = load_cerebras_qwen_baseline()
    assert frozen["same_frozen_top50"] is True
    assert frozen["same_minimal_json"] is True
    assert frozen["does_not_replace_cerebras_output"] is True
    assert frozen["verdict"] == "rejected_for_naive_rerank"
    assert frozen["headline"]["model"] == QWEN_MODEL
    assert frozen["headline"]["reasoning_effort"] == "low"
    assert frozen["headline"]["quality_reference"]["true_support"] == 24
    assert frozen["headline"]["summary"]["mean_candidate_recall"] == 1.0
    assert frozen["headline"]["summary"]["total_id_errors"] == 0
    assert frozen["headline"]["summary"]["total_reasoning_tokens"] == 13694
    assert frozen["headline"]["summary"]["cost_usd"] == 0.03929153
    golds = {row["gold_id"]: row for row in frozen["headline"]["golds"]}
    assert golds["auto-renewal"]["candidate_recall"] == 1.0
    assert golds["liability-secrecy-carveout"]["precision"] == 1.0
    assert golds["confidentiality"]["precision"] < 0.5
    assert RETRIEVAL_CONCLUSIONS["cerebras_qwen_does_not_replace_output"] is True

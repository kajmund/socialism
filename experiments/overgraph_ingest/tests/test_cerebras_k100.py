import json

from overgraph_ingest.cerebras.chosen import freeze_cerebras_medium_chosen
from overgraph_ingest.cerebras.client import CerebrasReply, EmptyCompletionError
from overgraph_ingest.cerebras.k100 import (
    freeze_cerebras_k100,
    run_cerebras_k100,
    _split_effects,
)
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.jev.candidates import GraphContext
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_cerebras_chosen_baseline,
    load_cerebras_k100_baseline,
)
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit


def _gold() -> RetrievalGold:
    return RetrievalGold(
        id="auto-renewal",
        query="Vilka avtal innehåller bestämmelser om automatisk förlängning?",
        relevant_units=[],
        hard_negatives=[],
        document_gold=("a.docx",),
    )


class _FakeCompleter:
    def complete(self, messages: list[dict[str, str]]) -> CerebrasReply:
        assert "Ingen motivering" in messages[1]["content"]
        assert "c100" in messages[1]["content"]
        return CerebrasReply(
            text='{"match":["c01","c51"],"uncertain":[]}',
            ttft_seconds=0.1,
            completion_seconds=0.2,
            prompt_tokens=400,
            completion_tokens=20,
            reasoning_tokens=10,
        )


def test_medium_minimal_is_the_quality_setting() -> None:
    frozen = freeze_cerebras_medium_chosen()
    assert frozen["verdict"] == "keep_medium_minimal"
    assert frozen["best_setting"] == "gpt-oss-120b-medium-minimal-json"
    assert frozen["do_not_tune_reasoning_on_same_five"] is True
    assert frozen["low_is_not_quality_equivalent"] is True
    assert frozen["next_isolated_experiment"] == "k100"
    assert frozen["k200_not_started"] is True
    assert frozen["second_opinion_not_started"] is True
    assert frozen["headline"]["summary"]["true_matches"] == 72
    assert RETRIEVAL_CONCLUSIONS["best_naive_rerank_setting"] == (
        "gpt-oss-120b-medium-minimal-json"
    )
    assert RETRIEVAL_CONCLUSIONS["do_not_tune_reasoning_on_same_five"] is True


def test_split_effects_separates_retrieval_gain_from_model_miss() -> None:
    split = _split_effects(
        previous_keys=[f"old{i}" for i in range(50)],
        new_keys=[f"old{i}" for i in range(50)] + [f"new{i}" for i in range(50)],
        corpus_keys={"old0", "new0", "missing"},
        match_keys={"new0"},
    )
    assert split["top50_overlap"] == 50
    assert split["relevant_in_frozen_50"] == 1
    assert split["relevant_in_100"] == 2
    assert split["retrieval_gain"] == 1
    assert split["still_missing"] == 1
    assert split["model_missed_from_k50"] == 1
    assert split["model_caught_gain"] == 1


def test_k100_freeze_does_not_start_k200() -> None:
    frozen = freeze_cerebras_k100(
        {
            "quality_reference": QUALITY_REFERENCE,
            "k": 100,
            "reference_k": 50,
            "model": "gpt-oss-120b",
            "setting": "medium",
            "variant": "minimal",
            "summary": {},
            "golds": [],
        }
    )
    assert frozen["k200_not_started"] is True
    assert frozen["second_opinion_not_started"] is True
    assert frozen["does_not_replace_cerebras_output"] is True


def test_k100_run_uses_injected_hits(tmp_path: object, monkeypatch: object) -> None:
    frozen = tmp_path / "frozen.json"
    frozen.write_text(
        json.dumps(
            {
                "k": 50,
                "golds": [
                    {
                        "gold_id": "auto-renewal",
                        "judgments": [{"id": f"c{i:02d}", "key": f"k{i:02d}"} for i in range(1, 51)],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    units = [
        StoredUnit(i, f"k{i:02d}", f"d{i}", "a.docx", f"text {i}", None, None)
        for i in range(1, 101)
    ]
    hits = [
        SearchHit(i, f"k{i:02d}", 1.0 / i, i, "a.docx", "a.docx", f"text {i}")
        for i in range(1, 101)
    ]

    class _Db:
        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "overgraph_ingest.cerebras.k100.open_database", lambda *_args, **_kwargs: _Db()
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.k100.resolve_dimension", lambda *_args, **_kwargs: 3072
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.k100.load_graph_context",
        lambda *_args, **_kwargs: GraphContext(units, {}, {}, {}),
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.k100._golds",
        lambda *_args, **_kwargs: [_gold()],
    )
    payload = run_cerebras_k100(
        frozen_path=frozen,
        client=_FakeCompleter(),
        hits_by_gold={"auto-renewal": hits},
    )
    assert payload["k"] == 100
    assert payload["k200_not_started"] is True
    assert payload["k50_cap_exhausted_reasoning"] is True
    assert payload["model_completes"] is True
    row = payload["golds"][0]
    assert row["effects"]["top50_overlap"] == 50
    assert row["true_matches"] == 0
    assert row["cost_per_true_match_usd"] is None


class _EmptyCompleter:
    def complete(self, messages: list[dict[str, str]]) -> CerebrasReply:
        raise EmptyCompletionError(
            finish_reason="length",
            reasoning_tokens=39997,
            prompt_tokens=7000,
            completion_tokens=40000,
            completion_seconds=16.0,
        )


def test_k100_records_retrieval_when_medium_emits_no_json(
    tmp_path: object, monkeypatch: object
) -> None:
    frozen = tmp_path / "frozen.json"
    frozen.write_text(
        json.dumps(
            {
                "k": 50,
                "golds": [
                    {
                        "gold_id": "auto-renewal",
                        "judgments": [{"id": f"c{i:02d}", "key": f"k{i:02d}"} for i in range(1, 51)],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    units = [
        StoredUnit(i, f"k{i:02d}", f"d{i}", "a.docx", f"text {i}", None, None)
        for i in range(1, 101)
    ]
    hits = [
        SearchHit(i, f"k{i:02d}", 1.0 / i, i, "a.docx", "a.docx", f"text {i}")
        for i in range(1, 101)
    ]

    class _Db:
        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "overgraph_ingest.cerebras.k100.open_database", lambda *_args, **_kwargs: _Db()
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.k100.resolve_dimension", lambda *_args, **_kwargs: 3072
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.k100.load_graph_context",
        lambda *_args, **_kwargs: GraphContext(units, {}, {}, {}),
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.k100._golds",
        lambda *_args, **_kwargs: [_gold()],
    )
    payload = run_cerebras_k100(
        frozen_path=frozen,
        client=_EmptyCompleter(),
        hits_by_gold={"auto-renewal": hits},
    )
    assert payload["model_completes"] is False
    assert payload["model_failure"]["reasoning_tokens"] == 39997
    assert payload["golds"][0]["model_status"] == "empty_completion"
    assert payload["golds"][0]["retrieval_gain"] == 0


def test_medium_chosen_baseline() -> None:
    frozen = load_cerebras_chosen_baseline()
    assert frozen["verdict"] == "keep_medium_minimal"
    assert frozen["do_not_tune_reasoning_on_same_five"] is True
    assert frozen["headline"]["summary"]["true_matches"] == 72


def test_cerebras_k100_baseline() -> None:
    frozen = load_cerebras_k100_baseline()
    assert frozen["k200_not_started"] is True
    assert frozen["second_opinion_not_started"] is True
    assert frozen["headline"]["model_completes"] is False
    assert frozen["headline"]["model_failure"]["reasoning_tokens"] == 39997
    assert frozen["headline"]["summary"]["mean_top50_overlap"] == 50.0
    assert frozen["headline"]["summary"]["total_retrieval_gain"] == 7
    golds = {row["gold_id"]: row for row in frozen["headline"]["golds"]}
    assert golds["liability-cap"]["effects"]["retrieval_gain"] == 6
    assert golds["confidentiality"]["effects"]["retrieval_gain"] == 1
    assert golds["notice-period"]["effects"]["still_missing"] == 2
    assert RETRIEVAL_CONCLUSIONS["cerebras_k100_medium_does_not_complete"] is True
    assert RETRIEVAL_CONCLUSIONS["cerebras_k100_one_shot_quality_unmeasured"] is True
    assert RETRIEVAL_CONCLUSIONS["cerebras_k100_does_not_prove_one_shot_impossible"] is True
    assert RETRIEVAL_CONCLUSIONS["cerebras_k100_cap_raised_to_measure_json"] is True

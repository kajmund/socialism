import json

from overgraph_ingest.cerebras.client import CerebrasReply, EmptyCompletionError
from overgraph_ingest.cerebras.split50 import (
    SPLIT50_MAX_COMPLETION_TOKENS,
    freeze_cerebras_split50,
    group_effects,
    run_cerebras_split50,
)
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.jev.candidates import GraphContext
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_cerebras_split50_baseline,
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


class _SplitCompleter:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, messages: list[dict[str, str]]) -> CerebrasReply:
        content = messages[1]["content"]
        self.prompts.append(content)
        assert "Ingen motivering" in content
        assert "c50\n" in content
        assert "c51" not in content
        assert "text 100" not in content or "text 51" in content
        match = "c01" if len(self.prompts) == 1 else "c01"
        return CerebrasReply(
            text=f'{{"match":["{match}"],"uncertain":[]}}',
            ttft_seconds=0.1,
            completion_seconds=0.2,
            prompt_tokens=400,
            completion_tokens=20,
            reasoning_tokens=10,
        )


def _frozen_top50(tmp_path: object) -> object:
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
    return frozen


def _hits() -> list[SearchHit]:
    return [
        SearchHit(i, f"k{i:02d}", 1.0 / i, i, "a.docx", "a.docx", f"text {i}")
        for i in range(1, 101)
    ]


def _units() -> list[StoredUnit]:
    return [StoredUnit(i, f"k{i:02d}", f"d{i}", "a.docx", f"text {i}", None, None) for i in range(1, 101)]


def _patch_db(monkeypatch: object, units: list[StoredUnit]) -> None:
    class _Db:
        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "overgraph_ingest.cerebras.split50.open_database", lambda *_args, **_kwargs: _Db()
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.split50.resolve_dimension", lambda *_args, **_kwargs: 3072
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.split50.load_graph_context",
        lambda *_args, **_kwargs: GraphContext(units, {}, {}, {}),
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.split50._golds",
        lambda *_args, **_kwargs: [_gold()],
    )


def test_group_effects_counts_lost_true_matches() -> None:
    effects = group_effects(
        previous_match_keys={"gold", "false"},
        batch_match_keys={"false", "new"},
        corpus_keys={"gold", "other"},
        first50_keys={"gold", "false", "new", "other"},
    )
    assert effects["lost_from_k50_true_matches"] == 1
    assert effects["lost_from_k50_true_match_keys"] == ["gold"]
    assert effects["new_on_k50_matches"] == 1


def test_split50_uses_two_local_batches(tmp_path: object, monkeypatch: object) -> None:
    completer = _SplitCompleter()
    _patch_db(monkeypatch, _units())
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.split50.relevant_keys",
        lambda *_args, **_kwargs: {"k01", "k51", "missing"},
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.split50.relevant_documents",
        lambda *_args, **_kwargs: {"a.docx"},
    )
    payload = run_cerebras_split50(
        frozen_path=_frozen_top50(tmp_path),
        client=completer,
        hits_by_gold={"auto-renewal": _hits()},
        previous_match_by_gold={"auto-renewal": {"k01"}},
    )
    assert payload["k"] == 100
    assert payload["batch_size"] == 50
    assert payload["calls_per_question"] == 2
    assert payload["sequential_calls"] is True
    assert payload["one_shot_k100_not_retried"] is True
    assert payload["does_not_change_reasoning"] is True
    assert payload["max_completion_tokens"] == SPLIT50_MAX_COMPLETION_TOKENS
    assert payload["max_completion_tokens"] == 8192
    assert payload["k100_diagnostic_cap"] == 40_000
    assert payload["k200_not_started"] is True
    assert payload["this_is_not_jev_batching"] is True
    assert len(completer.prompts) == 2
    assert "text 1" in completer.prompts[0]
    assert "text 50" in completer.prompts[0]
    assert "text 51" not in completer.prompts[0]
    assert "text 51" in completer.prompts[1]
    assert "text 100" in completer.prompts[1]
    assert "text 1\n" not in completer.prompts[1]
    row = payload["golds"][0]
    assert row["model_status"] == "ok"
    assert row["candidate_recall"] == 1.0
    assert row["corpus_recall"] == 2 / 3
    assert row["true_matches"] == 2
    assert row["effects"]["retrieval_gain"] == 1
    assert row["effects"]["still_missing"] == 1
    assert row["model_caught_gain"] == 1
    assert row["lost_from_k50_true_matches"] == 0
    assert row["group_effects"]["lost_from_k50_true_matches"] == 0
    assert row["batch_quality"]["first50"]["true_matches"] == 1
    assert row["batch_quality"]["second50"]["true_matches"] == 1
    assert row["model_seconds"] == 0.4
    assert row["prompt_tokens"] == 800
    assert row["completion_tokens"] == 40


def test_split50_records_lost_previous_true_match(tmp_path: object, monkeypatch: object) -> None:
    class _MissFirst:
        def complete(self, messages: list[dict[str, str]]) -> CerebrasReply:
            return CerebrasReply(
                text='{"match":[],"uncertain":[]}',
                ttft_seconds=0.1,
                completion_seconds=0.2,
                prompt_tokens=400,
                completion_tokens=20,
                reasoning_tokens=10,
            )

    _patch_db(monkeypatch, _units())
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.split50.relevant_keys",
        lambda *_args, **_kwargs: {"k01", "k51"},
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.split50.relevant_documents",
        lambda *_args, **_kwargs: {"a.docx"},
    )
    payload = run_cerebras_split50(
        frozen_path=_frozen_top50(tmp_path),
        client=_MissFirst(),
        hits_by_gold={"auto-renewal": _hits()},
        previous_match_by_gold={"auto-renewal": {"k01"}},
    )
    row = payload["golds"][0]
    assert row["lost_from_k50_true_matches"] == 1
    assert row["group_effects"]["lost_from_k50_true_match_keys"] == ["k01"]
    assert row["model_missed_from_k50"] == 1
    assert row["model_caught_gain"] == 0


class _EmptyThenOk:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages: list[dict[str, str]]) -> CerebrasReply:
        self.calls += 1
        if self.calls == 1:
            raise EmptyCompletionError(
                finish_reason="length",
                reasoning_tokens=8189,
                prompt_tokens=400,
                completion_tokens=8192,
                completion_seconds=2.0,
            )
        return CerebrasReply(
            text='{"match":["c01"],"uncertain":[]}',
            ttft_seconds=0.1,
            completion_seconds=0.2,
            prompt_tokens=400,
            completion_tokens=20,
            reasoning_tokens=10,
        )


def test_split50_attempts_second_batch_if_first_is_empty(
    tmp_path: object, monkeypatch: object
) -> None:
    completer = _EmptyThenOk()
    _patch_db(monkeypatch, _units())
    payload = run_cerebras_split50(
        frozen_path=_frozen_top50(tmp_path),
        client=completer,
        hits_by_gold={"auto-renewal": _hits()},
        previous_match_by_gold={"auto-renewal": {"k01"}},
    )
    assert completer.calls == 2
    row = payload["golds"][0]
    assert row["model_status"] == "incomplete"
    assert row["batches"][0]["status"] == "empty_completion"
    assert row["batches"][1]["status"] == "ok"
    assert payload["model_completes"] is False
    assert row.get("precision") is None


def test_split50_freeze_does_not_start_k200() -> None:
    frozen = freeze_cerebras_split50(
        {
            "quality_reference": QUALITY_REFERENCE,
            "k": 100,
            "batch_size": 50,
            "calls_per_question": 2,
            "model": "gpt-oss-120b",
            "setting": "medium",
            "variant": "minimal",
            "max_completion_tokens": 8192,
            "summary": {},
            "golds": [],
        }
    )
    assert frozen["k200_not_started"] is True
    assert frozen["second_opinion_not_started"] is True
    assert frozen["one_shot_k100_not_retried"] is True
    assert frozen["does_not_change_reasoning"] is True
    assert frozen["does_not_replace_cerebras_k100"] is True


def test_cerebras_split50_baseline() -> None:
    frozen = load_cerebras_split50_baseline()
    assert frozen["k200_not_started"] is True
    assert frozen["second_opinion_not_started"] is True
    assert frozen["one_shot_k100_not_retried"] is True
    assert frozen["does_not_change_reasoning"] is True
    assert frozen["headline"]["model_completes"] is True
    assert frozen["headline"]["max_completion_tokens"] == 8192
    assert frozen["headline"]["summary"]["mean_candidate_recall"] == 1.0
    assert frozen["headline"]["summary"]["total_true_matches"] == 79
    assert frozen["headline"]["summary"]["total_lost_from_k50_true_matches"] == 0
    assert frozen["headline"]["summary"]["total_model_caught_gain"] == 7
    assert frozen["headline"]["summary"]["mean_top50_overlap"] == 50.0
    golds = {row["gold_id"]: row for row in frozen["headline"]["golds"]}
    assert golds["liability-cap"]["true_matches"] == 34
    assert golds["confidentiality"]["true_matches"] == 7
    assert golds["notice-period"]["group_effects"]["lost_from_k50_true_matches"] == 0
    assert RETRIEVAL_CONCLUSIONS["cerebras_split50_completes"] is True


def test_k100_conclusions_do_not_overclaim() -> None:
    assert RETRIEVAL_CONCLUSIONS["cerebras_k100_medium_does_not_complete"] is True
    assert RETRIEVAL_CONCLUSIONS["cerebras_k100_one_shot_quality_unmeasured"] is True
    assert RETRIEVAL_CONCLUSIONS["cerebras_k100_does_not_prove_one_shot_impossible"] is True
    assert RETRIEVAL_CONCLUSIONS["cerebras_k100_cap_raised_to_measure_json"] is True

import json

import pytest

from overgraph_ingest.cerebras.evaluate import score_rerank
from overgraph_ingest.cerebras.client import CerebrasReply
from overgraph_ingest.cerebras.output import (
    freeze_cerebras_output,
    hydrate_candidates,
    run_cerebras_output,
)
from overgraph_ingest.jev.candidates import GraphContext
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.cerebras.prompt import (
    MATCH,
    MINIMAL,
    NO_MATCH,
    TASK,
    UNCERTAIN,
    build_messages,
    candidates_from_hits,
    parse_judgments,
    parse_minimal,
)
from overgraph_ingest.cerebras.run import freeze_cerebras_rerank
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_cerebras_output_baseline,
    load_cerebras_rerank_baseline,
)
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.search import SearchHit


def _hit(key: str, path: str, rank: int, text: str) -> SearchHit:
    return SearchHit(rank, key, 1.0 / rank, rank, path, path, text)


def _gold() -> RetrievalGold:
    return RetrievalGold(
        id="auto-renewal",
        query="Vilka avtal innehåller bestämmelser om automatisk förlängning?",
        relevant_units=[],
        hard_negatives=[],
        document_gold=("a.docx", "b.docx"),
    )


def test_task_is_formulation_presence() -> None:
    assert TASK == "formulation_presence"
    assert QUALITY_REFERENCE["true_support"] == 24
    assert RETRIEVAL_CONCLUSIONS["latest_quality_reference"] == "24/53"
    assert RETRIEVAL_CONCLUSIONS["cerebras_rerank_applied_to_v3"] is False
    assert RETRIEVAL_CONCLUSIONS["cerebras_rerank_is_formulation_presence"] is True


def test_parse_rejects_invented_and_missing_ids() -> None:
    candidates = candidates_from_hits(
        [_hit("k1", "a.docx", 1, "förlängs automatiskt"), _hit("k2", "b.docx", 2, "annat")]
    )
    messages = build_messages("förlängning", candidates)
    assert "c01" in messages[1]["content"]
    assert "gällande avtalsvillkor" in messages[1]["content"]
    parsed = parse_judgments(
        {
            "judgments": [
                {"id": "c01", "label": MATCH, "reason": "automatisk förlängning"},
                {"id": "c02", "label": NO_MATCH, "reason": "ingen förlängning"},
            ]
        },
        candidates,
    )
    assert [row.key for row in parsed] == ["k1", "k2"]
    with pytest.raises(ValueError, match="invented"):
        parse_judgments(
            {"judgments": [{"id": "unit_999", "label": MATCH, "reason": "x"}]},
            candidates,
        )
    with pytest.raises(ValueError, match="omitted"):
        parse_judgments(
            {"judgments": [{"id": "c01", "label": MATCH, "reason": "x"}]},
            candidates,
        )


def test_uncertain_is_not_match_and_all_match_has_low_precision() -> None:
    gold = _gold()
    candidates = candidates_from_hits(
        [
            _hit("rel", "a.docx", 1, "förlängs"),
            _hit("noise", "c.docx", 2, "annat"),
        ]
    )
    judgments = [
        parse_judgments(
            {
                "judgments": [
                    {"id": "c01", "label": UNCERTAIN, "reason": "osäkert"},
                    {"id": "c02", "label": NO_MATCH, "reason": "nej"},
                ]
            },
            candidates,
        )
    ][0]
    skipped = score_rerank(
        gold=gold,
        candidates=candidates,
        judgments=judgments,
        corpus_relevant_keys={"rel", "missing"},
        corpus_relevant_docs={"a.docx", "b.docx"},
    )
    assert skipped["precision"] == 0.0
    assert skipped["candidate_recall"] == 0.0
    assert skipped["uncertain"] == 1
    assert skipped["uncertain_relevant"] == 1
    greedy = score_rerank(
        gold=gold,
        candidates=candidates,
        judgments=parse_judgments(
            {
                "judgments": [
                    {"id": "c01", "label": MATCH, "reason": "ja"},
                    {"id": "c02", "label": MATCH, "reason": "ja"},
                ]
            },
            candidates,
        ),
        corpus_relevant_keys={"rel", "missing"},
        corpus_relevant_docs={"a.docx", "b.docx"},
    )
    assert greedy["precision"] == 0.5
    assert greedy["candidate_recall"] == 1.0
    assert greedy["corpus_recall"] == 0.5
    assert greedy["corpus_document_recall"] == 0.5
    assert greedy["retrieval_document_coverage"] == 0.5


def test_freeze_does_not_replace_official_paths() -> None:
    frozen = freeze_cerebras_rerank(
        {
            "quality_reference": QUALITY_REFERENCE,
            "k": 50,
            "model": "gpt-oss-120b",
            "summary": {"golds": 0},
            "golds": [],
        }
    )
    assert frozen["does_not_replace_c8"] is True
    assert frozen["does_not_replace_coverage_v3"] is True
    assert frozen["no_proof_evaluator"] is True
    assert frozen["task"] == TASK
    assert json.dumps(frozen)


def test_cerebras_rerank_baseline() -> None:
    frozen = load_cerebras_rerank_baseline()
    assert frozen["does_not_replace_c8"] is True
    assert frozen["does_not_replace_coverage_v3"] is True
    assert frozen["no_proof_evaluator"] is True
    assert frozen["task"] == TASK
    assert frozen["headline"]["quality_reference"]["true_support"] == 24
    assert frozen["headline"]["summary"]["mean_candidate_recall"] == 1.0
    golds = {row["gold_id"]: row for row in frozen["headline"]["golds"]}
    assert golds["auto-renewal"]["precision"] == 1.0
    assert golds["auto-renewal"]["corpus_recall"] == 1.0
    assert golds["liability-secrecy-carveout"]["precision"] == 1.0
    assert golds["confidentiality"]["candidate_recall"] == 1.0
    assert golds["confidentiality"]["precision"] < 0.5
    assert RETRIEVAL_CONCLUSIONS["cerebras_rerank_does_not_replace_c8"] is True


def test_minimal_output_treats_omitted_ids_as_no_match() -> None:
    candidates = candidates_from_hits(
        [_hit("k1", "a.docx", 1, "förlängs"), _hit("k2", "b.docx", 2, "annat")]
    )
    messages = build_messages("förlängning", candidates, variant=MINIMAL)
    assert "motivering" in messages[1]["content"]
    parsed, errors = parse_minimal(
        {"match": ["c01"], "uncertain": ["unit_999"]},
        candidates,
    )
    assert [row.label for row in parsed] == [MATCH, NO_MATCH]
    assert errors["invented"] == ["unit_999"]
    assert errors["duplicates"] == []
    parsed, errors = parse_minimal(
        {"match": ["c01"], "uncertain": ["c01"]},
        candidates,
    )
    assert parsed[0].label == MATCH
    assert errors["duplicates"] == ["c01"]


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


def test_hydrate_keeps_frozen_candidate_order() -> None:
    units = {
        "k2": StoredUnit(2, "k2", "d2", "b.docx", "andra klausulen", None, None),
        "k1": StoredUnit(1, "k1", "d1", "a.docx", "första klausulen", None, None),
    }
    candidates = hydrate_candidates(
        [{"id": "c01", "key": "k2"}, {"id": "c02", "key": "k1"}],
        units,
    )
    assert [row.short_id for row in candidates] == ["c01", "c02"]
    assert [row.key for row in candidates] == ["k2", "k1"]
    assert candidates[0].text == "andra klausulen"


def test_output_run_uses_frozen_keys_not_new_retrieval(
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
                        "precision": 1.0,
                        "candidate_recall": 1.0,
                        "completion_tokens": 80,
                        "ttft_seconds": 1.0,
                        "model_seconds": 2.0,
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
    units = [
        StoredUnit(1, "k1", "d1", "a.docx", "förlängs automatiskt", None, None),
        StoredUnit(2, "k2", "d2", "b.docx", "annat", None, None),
    ]

    class _Db:
        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "overgraph_ingest.cerebras.output.open_database", lambda *_args, **_kwargs: _Db()
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.output.resolve_dimension", lambda *_args, **_kwargs: 3072
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.output.load_graph_context",
        lambda *_args, **_kwargs: GraphContext(units, {}, {}, {}),
    )
    monkeypatch.setattr(
        "overgraph_ingest.cerebras.output._golds",
        lambda *_args, **_kwargs: [_gold()],
    )
    payload = run_cerebras_output(frozen_path=frozen, client=_FakeCompleter())
    assert payload["same_frozen_top50"] is True
    assert payload["no_new_retrieval"] is True
    row = payload["golds"][0]
    assert row["retrieval_seconds"] == 0.0
    assert row["completion_tokens"] == 8
    assert row["id_errors"] == 0
    assert row["delta"]["completion_tokens"] == -72
    assert [item["key"] for item in row["judgments"]] == ["k1", "k2"]


def test_output_freeze_does_not_replace_rerank() -> None:
    frozen = freeze_cerebras_output(
        {
            "quality_reference": QUALITY_REFERENCE,
            "k": 50,
            "model": "gpt-oss-120b",
            "summary": {"golds": 0},
            "golds": [],
        }
    )
    assert frozen["does_not_replace_cerebras_rerank"] is True
    assert frozen["same_frozen_top50"] is True
    assert frozen["no_new_retrieval"] is True


def test_cerebras_output_baseline() -> None:
    frozen = load_cerebras_output_baseline()
    assert frozen["same_frozen_top50"] is True
    assert frozen["no_new_retrieval"] is True
    assert frozen["does_not_replace_cerebras_rerank"] is True
    assert frozen["headline"]["quality_reference"]["true_support"] == 24
    assert frozen["headline"]["summary"]["mean_candidate_recall"] == 1.0
    assert frozen["headline"]["summary"]["total_id_errors"] == 0
    assert frozen["headline"]["summary"]["total_completion_tokens"] == 9588
    assert frozen["headline"]["summary"]["total_completion_token_delta"] == -4283
    assert frozen["headline"]["summary"]["total_visible_json_chars"] < 2000
    golds = {row["gold_id"]: row for row in frozen["headline"]["golds"]}
    assert golds["auto-renewal"]["precision"] == 1.0
    assert golds["notice-period"]["precision"] == 0.55
    assert golds["liability-secrecy-carveout"]["precision"] == 1.0
    assert golds["liability-cap"]["precision"] < 0.9
    assert golds["confidentiality"]["candidate_recall"] == 1.0
    assert RETRIEVAL_CONCLUSIONS["cerebras_output_does_not_replace_rerank"] is True

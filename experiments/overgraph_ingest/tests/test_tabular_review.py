from __future__ import annotations

import json
from pathlib import Path

import pytest

from overgraph_ingest.cerebras.client import CerebrasReply
from overgraph_ingest.jev.candidates import context_from_units
from overgraph_ingest.jev.client import JevResult, JevUsage
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_review_baseline,
)
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.tabular.cells import VARIANT_A, VARIANT_B, VARIANT_C, run_cell
from overgraph_ingest.tabular.contract import (
    ANSWERED,
    NOT_FOUND,
    UNCERTAIN,
    source_ref,
)
from overgraph_ingest.tabular.evaluate import (
    CORRECT_NOT_FOUND,
    FALSE_ANSWER,
    MISS,
    TRUE_ANSWER,
    compare_variants,
    score_cell,
    summarize,
)
from overgraph_ingest.tabular.freeze import freeze_tabular_review, write_tabular_review_baseline
from overgraph_ingest.tabular.gold import (
    QUESTION_IDS,
    SELECTED_DOCUMENTS,
    USER_QUESTIONS,
    load_tabular_golds,
)
from overgraph_ingest.tabular.jev_io import ANSWER
from overgraph_ingest.tabular.navigate import (
    AMBIGUOUS,
    RESOLVE_REFERENCE,
    option_by_choice,
    valid_operations,
)
from overgraph_ingest.tabular.reuse import NOT_REUSED, REUSED
from overgraph_ingest.tabular.run import run_tabular_review
from overgraph_ingest.tabular.search import document_local_rank, recall_at

ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = ROOT / "retrieval_gold"
EXTRA_CORPUS = ROOT / "data" / "extra_corpus"
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"
INGEST = ROOT / "baselines" / "phase1-sequential-100-docx.json"


def _unit(
    key: str,
    path: str,
    text: str,
    *,
    structure_id: str = "s1",
    sequence: int = 1,
    dense: list[float] | None = None,
    sparse: list[tuple[int, float]] | None = None,
    document_id: str | None = None,
) -> StoredUnit:
    return StoredUnit(
        node_id=sequence,
        key=key,
        document_id=document_id or f"doc-{path}",
        relative_path=path,
        text=text,
        dense=dense if dense is not None else [1.0, 0.0],
        sparse=sparse if sparse is not None else [(1, 1.0)],
        structure_id=structure_id,
        sequence=sequence,
        char_start=0,
        char_end=len(text),
    )


class ScriptedJev:
    def __init__(self, decisions: list[str] | None = None) -> None:
        self.decisions = list(decisions or [])
        self.calls = 0

    def ask(self, *, state, questions, model, timeout_seconds):
        self.calls += 1
        if "decision" in questions:
            criteria = questions["decision"]["criteria"]
            if self.decisions:
                choice = self.decisions.pop(0)
            else:
                hop = next(
                    (key for key in criteria if key.startswith(f"{RESOLVE_REFERENCE}:")),
                    None,
                )
                choice = hop or ANSWER
            return _jev({"decision": {"choice": choice}})
        if "status" in questions:
            source = next(
                (
                    key
                    for key, text in questions["source"]["criteria"].items()
                    if key != "none" and "förlängs automatiskt" in text
                ),
                next(
                    (key for key in questions["source"]["criteria"] if key != "none"),
                    "none",
                ),
            )
            excerpt = next(
                (
                    key
                    for key, text in questions["excerpt"]["criteria"].items()
                    if key != "none" and "förlängs automatiskt" in text
                ),
                next(
                    (key for key in questions["excerpt"]["criteria"] if key != "none"),
                    "none",
                ),
            )
            return _jev(
                {
                    "status": {"choice": ANSWERED},
                    "source": {"choice": source},
                    "excerpt": {"choice": excerpt},
                }
            )
        answers = {}
        for key in questions:
            text = next(
                row["text"]
                for row in state["candidates"]
                if row["id"] == key
            )
            if "förlängs automatiskt" in text:
                predicted = "YES"
            elif "punkt" in text.lower():
                predicted = "UNCERTAIN"
            else:
                predicted = "NO"
            answers[key] = {"choice": predicted}
        return _jev(answers)


class FakeCerebras:
    def __init__(self, payload: dict[str, str]) -> None:
        self.payload = payload

    def complete(self, messages: list[dict[str, str]]) -> CerebrasReply:
        return CerebrasReply(
            text=json.dumps(self.payload, ensure_ascii=False),
            ttft_seconds=0.01,
            completion_seconds=0.02,
            prompt_tokens=12,
            completion_tokens=8,
        )


def _jev(answers: dict[str, object]) -> JevResult:
    return JevResult(
        answers=answers,
        model="jev-latest",
        latency_ms=1.0,
        usage=JevUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4),
        raw={"answers": answers},
    )


def test_inventory_reuses_hops_not_hop_always() -> None:
    assert "hops" in REUSED
    assert "classify" in REUSED
    assert NOT_REUSED["coverage_v3"].startswith("run_coverage_v3")
    assert RETRIEVAL_CONCLUSIONS["tabular_review"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_review_does_not_replace_c8"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_cell_accuracy_is_not_24_53"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_second_run_100_not_started"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_selection_is_diagnostic"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_jev_requested_no_hops"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_a_did_not_beat_b"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_cerebras_did_not_beat_jev"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_quality_reference"] == "jev_b"
    assert RETRIEVAL_CONCLUSIONS["tabular_model_comparisons"] == "paused"
    assert RETRIEVAL_CONCLUSIONS["do_not_test_more_tabular_models"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_build_tabular_navigation"] is True


def test_frozen_selection_is_twenty_documents_and_five_questions() -> None:
    assert len(SELECTED_DOCUMENTS) == 20
    assert len(QUESTION_IDS) == 5
    assert USER_QUESTIONS["notice-period"].startswith("Vilken uppsägningstid")
    golds = load_tabular_golds(GOLD_DIR)
    assert {gold.id for gold in golds} == set(QUESTION_IDS)
    assert all(gold.split == "seen" for gold in golds)


@pytest.mark.skipif(not EXTRA_CORPUS.is_dir(), reason="extra_corpus is not present")
def test_selected_documents_exist_in_extra_corpus() -> None:
    missing = [name for name in SELECTED_DOCUMENTS if not (EXTRA_CORPUS / name).is_file()]
    assert missing == []


def test_document_local_rank_does_not_leak_other_documents() -> None:
    path_a = "Avtal_17_Hyresavtal_lokal.docx"
    path_b = "Avtal_01_Tillsvidareanstallningsavtal.docx"
    units = [
        _unit("gold", path_a, "Avtalet förlängs automatiskt med tolv månader.", dense=[1.0, 0.0], sparse=[(1, 1.0)]),
        _unit("other-doc", path_b, "Avtalet förlängs automatiskt med tolv månader.", sequence=2, dense=[1.0, 0.0], sparse=[(1, 1.0)]),
        _unit("noise", path_a, "Parterna ska hålla information hemlig.", sequence=3, dense=[0.0, 1.0], sparse=[(2, 1.0)]),
    ]
    ranked = document_local_rank(
        units,
        path_a,
        dense_query=[1.0, 0.0],
        sparse_query=[(1, 1.0)],
    )
    assert {hit.relative_path for hit in ranked} == {path_a}
    assert ranked[0].key == "gold"
    assert recall_at(ranked, {"gold"})["recall@5"] == 1.0
    assert recall_at(ranked, {"gold"})["recall@3"] == 1.0
    assert recall_at(ranked, {"gold"})["recall@10"] == 1.0


def test_answered_requires_exact_excerpt() -> None:
    unit = _unit("u1", "a.docx", "Avtalet förlängs automatiskt med tolv månader.")
    ok = source_ref(unit, "förlängs automatiskt")
    bad = source_ref(unit, "förlängs tyst")
    assert ok.validated is True
    assert bad.validated is False


def test_resolve_reference_is_not_substituted_when_absent() -> None:
    start = _unit(
        "start",
        "a.docx",
        "Begränsningarna gäller inte vid brott mot punkt 99.",
        structure_id="s-6",
    )
    other = _unit(
        "cap",
        "a.docx",
        "Ansvaret är begränsat till 500 000 kronor.",
        structure_id="s-12",
        sequence=2,
    )
    structures = {
        "s-6": {"parent_id": "root", "clause_number": "6", "title": "6. Begränsningarna"},
        "s-12": {"parent_id": "root", "clause_number": "12", "title": "12. Ansvar"},
    }
    offer = valid_operations(start, [start, other], structures, set())
    assert all(option.operation != RESOLVE_REFERENCE for option in offer.options)
    assert offer.reports[0]["status"] == "ABSENT"
    assert option_by_choice(offer, f"{RESOLVE_REFERENCE}:cap") is None


def test_same_unit_can_be_next_and_resolve_reference() -> None:
    start = _unit(
        "start",
        "a.docx",
        "Se punkt 8 för villkoren.",
        structure_id="s-6",
    )
    target = _unit(
        "clause8",
        "a.docx",
        "Avtalet förlängs automatiskt med tolv månader.",
        structure_id="s-8",
        sequence=2,
    )
    structures = {
        "s-6": {"parent_id": "root", "clause_number": "6", "title": "6. Hänvisning"},
        "s-8": {"parent_id": "root", "clause_number": "8", "title": "8. Förlängning"},
    }
    offer = valid_operations(start, [start, target], structures, set())
    operations = {option.operation for option in offer.options if option.target_key == "clause8"}
    assert operations >= {"NEXT", RESOLVE_REFERENCE}


def test_ambiguous_reference_is_reported_not_picked() -> None:
    start = _unit(
        "start",
        "a.docx",
        "Se punkt 8 för villkoren.",
        structure_id="s-1",
    )
    first = _unit("a", "a.docx", "8. Första", structure_id="s-8a", sequence=2)
    second = _unit("b", "a.docx", "8. Andra", structure_id="s-8b", sequence=3)
    structures = {
        "s-1": {"parent_id": "root", "clause_number": "1", "title": "1. Hänvisning"},
        "s-8a": {"parent_id": "root", "clause_number": "8", "title": "8. Första"},
        "s-8b": {"parent_id": "root", "clause_number": "8", "title": "8. Andra"},
    }
    offer = valid_operations(start, [start, first, second], structures, set())
    assert all(option.operation != RESOLVE_REFERENCE for option in offer.options)
    assert offer.reports[0]["status"] == AMBIGUOUS


def test_variant_b_answers_without_navigation() -> None:
    path = "Avtal_17_Hyresavtal_lokal.docx"
    gold_text = "Avtalet förlängs automatiskt med tolv månader."
    units = [
        _unit("gold", path, gold_text),
        _unit("noise", path, "Parterna ska samråda.", sequence=2, dense=[0.0, 1.0], sparse=[(2, 1.0)]),
    ]
    result = run_cell(
        variant=VARIANT_B,
        relative_path=path,
        question_id="auto-renewal",
        user_question=USER_QUESTIONS["auto-renewal"],
        classify_question="Innehåller texten en automatisk förlängning?",
        units=units,
        context=context_from_units(units, {"s1": {"title": "Tid"}}),
        dense_query=[1.0, 0.0],
        sparse_query=[(1, 1.0)],
        relevant_keys={"gold"},
        jev=ScriptedJev(),
        cerebras=None,
        jev_model="jev-latest",
        timeout_seconds=1.0,
    )
    assert result.status == ANSWERED
    assert result.navigation_steps == 0
    assert result.sources[0].validated is True
    assert result.source_unit_ids == ["gold"]


def test_variant_c_rejects_invented_excerpt() -> None:
    path = "Avtal_17_Hyresavtal_lokal.docx"
    text = "Avtalet förlängs automatiskt med tolv månader."
    units = [_unit("gold", path, text)]
    result = run_cell(
        variant=VARIANT_C,
        relative_path=path,
        question_id="auto-renewal",
        user_question=USER_QUESTIONS["auto-renewal"],
        classify_question="x",
        units=units,
        context=context_from_units(units, {}),
        dense_query=[1.0, 0.0],
        sparse_query=[(1, 1.0)],
        relevant_keys={"gold"},
        jev=None,
        cerebras=FakeCerebras(
            {
                "status": ANSWERED,
                "answer": "Ja",
                "source_unit_id": "gold",
                "excerpt": "påhittat citat",
            }
        ),
        jev_model="jev-latest",
        timeout_seconds=1.0,
    )
    assert result.status == UNCERTAIN
    assert result.notes == "citation_failed"
    assert result.sources == []


def test_variant_a_navigates_then_answers() -> None:
    path = "Avtal_49_IT_drift_hostingavtal.docx"
    start = _unit(
        "start",
        path,
        "Begränsningarna gäller inte vid brott mot punkt 8.",
        structure_id="s-6",
        dense=[1.0, 0.0],
        sparse=[(1, 1.0)],
    )
    target = _unit(
        "clause8",
        path,
        "Avtalet förlängs automatiskt med tolv månader.",
        structure_id="s-8",
        sequence=2,
        dense=[0.0, 1.0],
        sparse=[(2, 1.0)],
    )
    units = [start, target]
    structures = {
        "s-6": {"parent_id": "root", "clause_number": "6", "title": "6. Hänvisning"},
        "s-8": {"parent_id": "root", "clause_number": "8", "title": "8. Förlängning"},
    }
    result = run_cell(
        variant=VARIANT_A,
        relative_path=path,
        question_id="auto-renewal",
        user_question=USER_QUESTIONS["auto-renewal"],
        classify_question="Innehåller texten en automatisk förlängning?",
        units=units,
        context=context_from_units(units, structures),
        dense_query=[1.0, 0.0],
        sparse_query=[(1, 1.0)],
        relevant_keys={"clause8"},
        jev=ScriptedJev(),
        cerebras=None,
        jev_model="jev-latest",
        timeout_seconds=1.0,
        top_k=1,
    )
    assert result.navigation_steps == 1
    assert result.navigation[0]["operation"] == RESOLVE_REFERENCE
    assert result.navigation[0]["fetched"] == "clause8"
    assert result.navigation[0]["substituted"] is False
    assert result.status == ANSWERED
    assert result.source_unit_ids == ["clause8"]


def test_budget_stop_is_uncertain_not_verified_absence() -> None:
    path = "a.docx"
    start = _unit(
        "start",
        path,
        "Se punkt 8 för villkoren.",
        structure_id="s-6",
    )
    target = _unit(
        "clause8",
        path,
        "Avtalet förlängs automatiskt med tolv månader.",
        structure_id="s-8",
        sequence=2,
        dense=[0.0, 1.0],
        sparse=[(2, 1.0)],
    )
    units = [start, target]
    structures = {
        "s-6": {"parent_id": "root", "clause_number": "6", "title": "6. Hänvisning"},
        "s-8": {"parent_id": "root", "clause_number": "8", "title": "8. Förlängning"},
    }
    result = run_cell(
        variant=VARIANT_A,
        relative_path=path,
        question_id="auto-renewal",
        user_question=USER_QUESTIONS["auto-renewal"],
        classify_question="x",
        units=units,
        context=context_from_units(units, structures),
        dense_query=[1.0, 0.0],
        sparse_query=[(1, 1.0)],
        relevant_keys={"clause8"},
        jev=ScriptedJev([f"{RESOLVE_REFERENCE}:clause8"]),
        cerebras=None,
        jev_model="jev-latest",
        timeout_seconds=1.0,
        top_k=1,
        max_nav_steps=0,
    )
    assert result.status == UNCERTAIN
    assert result.budget_exhausted is True
    assert result.notes == "budget_exhausted"
    assert result.navigation_steps == 0


def test_navigation_alone_does_not_answer() -> None:
    path = "a.docx"
    start = _unit(
        "start",
        path,
        "Se punkt 8 för villkoren.",
        structure_id="s-6",
    )
    target = _unit(
        "clause8",
        path,
        "Avtalet förlängs automatiskt med tolv månader.",
        structure_id="s-8",
        sequence=2,
        dense=[0.0, 1.0],
        sparse=[(2, 1.0)],
    )
    units = [start, target]
    structures = {
        "s-6": {"parent_id": "root", "clause_number": "6", "title": "6. Hänvisning"},
        "s-8": {"parent_id": "root", "clause_number": "8", "title": "8. Förlängning"},
    }
    result = run_cell(
        variant=VARIANT_A,
        relative_path=path,
        question_id="auto-renewal",
        user_question=USER_QUESTIONS["auto-renewal"],
        classify_question="x",
        units=units,
        context=context_from_units(units, structures),
        dense_query=[1.0, 0.0],
        sparse_query=[(1, 1.0)],
        relevant_keys={"clause8"},
        jev=ScriptedJev(
            [f"{RESOLVE_REFERENCE}:clause8", UNCERTAIN]
        ),
        cerebras=None,
        jev_model="jev-latest",
        timeout_seconds=1.0,
        top_k=1,
    )
    assert result.navigation_steps == 1
    assert result.status == UNCERTAIN
    assert result.answer == ""


def test_score_requires_gold_citation_for_true_answer() -> None:
    path = "a.docx"
    unit = _unit("gold", path, "Avtalet förlängs automatiskt med tolv månader.")
    result = run_cell(
        variant=VARIANT_B,
        relative_path=path,
        question_id="auto-renewal",
        user_question=USER_QUESTIONS["auto-renewal"],
        classify_question="x",
        units=[unit],
        context=context_from_units([unit], {}),
        dense_query=[1.0, 0.0],
        sparse_query=[(1, 1.0)],
        relevant_keys={"gold"},
        jev=ScriptedJev(),
        cerebras=None,
        jev_model="jev-latest",
        timeout_seconds=1.0,
    )
    scored = score_cell(result, {"gold"})
    assert scored["outcome"] == TRUE_ANSWER
    missed = score_cell(result, set())
    assert missed["outcome"] == FALSE_ANSWER


def test_run_compares_three_variants_synchronously() -> None:
    path = "Avtal_17_Hyresavtal_lokal.docx"
    text = "Avtalet förlängs automatiskt med tolv månader."
    units = [_unit("gold", path, text)]
    golds = [
        RetrievalGold(
            id=question_id,
            query=USER_QUESTIONS[question_id],
            classify_question="Innehåller texten bestämmelsen?",
            relevant_units=[GoldSpan(path, "förlängs automatiskt")]
            if question_id == "auto-renewal"
            else [],
            hard_negatives=[],
        )
        for question_id in QUESTION_IDS
    ]
    queries = {question_id: ([1.0, 0.0], [(1, 1.0)]) for question_id in QUESTION_IDS}
    payload = run_tabular_review(
        documents=(path,),
        golds=golds,
        units=units,
        structures={},
        queries=queries,
        jev=ScriptedJev(),
        cerebras=FakeCerebras(
            {
                "status": ANSWERED,
                "answer": "Ja, avtalet förlängs automatiskt.",
                "source_unit_id": "gold",
                "excerpt": "förlängs automatiskt",
            }
        ),
    )
    assert payload["synchronous"] is True
    assert payload["same_mapping"] == GOLD_MAP_VERSION
    assert len(payload["cells"]) == 15
    variants = {row["variant"] for row in payload["cells"]}
    assert variants == {VARIANT_A, VARIANT_B, VARIANT_C}
    assert payload["comparison"]["variants"]["A"]["cells"] == 5
    assert payload["not_comparable_to_24_53"] is True
    assert payload["selection_is_diagnostic"] is True
    assert payload["headline"]["selection_is_not_general_quality"] is True


def test_freeze_does_not_overwrite_existing_baselines(tmp_path: Path) -> None:
    assert C8.is_file()
    assert INGEST.is_file()
    payload = {
        "selection": list(SELECTED_DOCUMENTS),
        "questions": [],
        "k": 5,
        "comparison": {"variants": {}},
        "cost": {},
        "errors": {},
        "wall_seconds": 1.0,
        "cells": [],
        "scored": [],
        "reuse": {"reused": REUSED, "not_reused": NOT_REUSED},
    }
    first = tmp_path / "phase2-tabular-review-v1.json"
    write_tabular_review_baseline(payload, first)
    with pytest.raises(FileExistsError):
        write_tabular_review_baseline(payload, first)
    frozen = freeze_tabular_review(payload)
    assert frozen["does_not_replace_c8"] is True
    assert frozen["does_not_replace_coverage_v3"] is True
    assert frozen["no_socialism_integration"] is True
    assert frozen["selection_is_diagnostic"] is True


def test_frozen_tabular_review_is_diagnostic_and_has_no_hops() -> None:
    frozen = load_tabular_review_baseline()
    headline = frozen["headline"]
    assert frozen["selection_is_diagnostic"] is True
    assert headline["selection_is_not_general_quality"] is True
    assert headline["cell_accuracy"] == {"A": 0.77, "B": 0.78, "C": 0.71}
    assert headline["navigation"]["requested_navigation"] == 0
    assert headline["navigation"]["answered_directly"] == 100
    assert len(frozen["cells"]) == 300


def test_summarize_reports_new_metrics() -> None:
    path = "a.docx"
    unit = _unit("gold", path, "Avtalet förlängs automatiskt med tolv månader.")
    answered = run_cell(
        variant=VARIANT_B,
        relative_path=path,
        question_id="auto-renewal",
        user_question=USER_QUESTIONS["auto-renewal"],
        classify_question="x",
        units=[unit],
        context=context_from_units([unit], {}),
        dense_query=[1.0, 0.0],
        sparse_query=[(1, 1.0)],
        relevant_keys={"gold"},
        jev=ScriptedJev(),
        cerebras=None,
        jev_model="jev-latest",
        timeout_seconds=1.0,
    )
    empty = run_cell(
        variant=VARIANT_B,
        relative_path="missing.docx",
        question_id="notice-period",
        user_question=USER_QUESTIONS["notice-period"],
        classify_question="x",
        units=[unit],
        context=context_from_units([unit], {}),
        dense_query=[1.0, 0.0],
        sparse_query=[(1, 1.0)],
        relevant_keys=set(),
        jev=ScriptedJev(),
        cerebras=None,
        jev_model="jev-latest",
        timeout_seconds=1.0,
    )
    assert empty.status == NOT_FOUND
    rows = [score_cell(answered, {"gold"}), score_cell(empty, set())]
    summary = summarize(rows)
    assert summary["cell_accuracy"] == 1.0
    assert summary["outcomes"][TRUE_ANSWER] == 1
    assert summary["outcomes"][CORRECT_NOT_FOUND] == 1
    compared = compare_variants(
        [{**rows[0], "variant": "A"}, {**rows[0], "variant": "B"}]
    )
    assert compared["answer_improvement_a_vs_b"] == 0.0
    assert compared["navigation"]["answered_directly"] == 1
    assert compared["navigation"]["requested_navigation"] == 0


def test_answer_correctness_is_not_citation_relevance() -> None:
    path = "a.docx"
    unit = _unit("noise", path, "Avtalet förlängs automatiskt med tolv månader.")
    result = run_cell(
        variant=VARIANT_B,
        relative_path=path,
        question_id="auto-renewal",
        user_question=USER_QUESTIONS["auto-renewal"],
        classify_question="x",
        units=[unit],
        context=context_from_units([unit], {}),
        dense_query=[1.0, 0.0],
        sparse_query=[(1, 1.0)],
        relevant_keys={"gold"},
        jev=ScriptedJev(),
        cerebras=None,
        jev_model="jev-latest",
        timeout_seconds=1.0,
    )
    scored = score_cell(result, {"gold"})
    assert result.status == ANSWERED
    assert scored["answer_correct"] is True
    assert scored["citation_grounded"] is True
    assert scored["citation_relevant"] is False
    assert scored["outcome"] == FALSE_ANSWER


def test_navigation_improvement_is_paired_against_b() -> None:
    path = "a.docx"
    a_row = {
        "relative_path": path,
        "question_id": "auto-renewal",
        "variant": "A",
        "status": ANSWERED,
        "outcome": TRUE_ANSWER,
        "full_success": True,
        "answer_correct": True,
        "citation_grounded": True,
        "citation_relevant": True,
        "gold_positive": True,
        "citation_accurate": True,
        "grounded_gold": True,
        "budget_exhausted": False,
        "navigation_steps": 1,
        "requested_navigation": True,
        "answered_directly": False,
        "seed_has_gold": False,
        "fetched_relevant": True,
        "wrong_path": False,
        "navigation_successes": 1,
        "navigation_failures": 0,
        "recall@3": 0.0,
        "recall@5": 0.0,
        "recall@10": 0.0,
        "jev_calls": 4,
        "cerebras_calls": 0,
        "cell_seconds": 1.0,
        "retrieve_seconds": 0.1,
        "classify_seconds": 0.2,
        "navigate_seconds": 0.3,
        "answer_seconds": 0.4,
        "notes": "",
    }
    b_miss = {
        **a_row,
        "variant": "B",
        "status": NOT_FOUND,
        "outcome": MISS,
        "full_success": False,
        "answer_correct": False,
        "citation_grounded": False,
        "citation_relevant": False,
        "citation_accurate": False,
        "grounded_gold": False,
        "navigation_steps": 0,
        "requested_navigation": False,
        "answered_directly": False,
        "fetched_relevant": False,
        "navigation_successes": 0,
    }
    compared = compare_variants([a_row, b_miss])
    assert compared["navigation"]["requested_navigation"] == 1
    assert compared["navigation"]["navigation_improved"] == 1
    assert compared["navigation"]["unnecessary_navigation"] == 0
    unnecessary = compare_variants([a_row, {**b_miss, **{
        "status": ANSWERED,
        "outcome": TRUE_ANSWER,
        "full_success": True,
        "answer_correct": True,
        "citation_relevant": True,
        "citation_grounded": True,
    }}])
    assert unnecessary["navigation"]["unnecessary_navigation"] == 1
    assert unnecessary["navigation"]["navigation_improved"] == 0

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from overgraph_ingest.benchmarks.corpus import write_lettered_clause_docx
from overgraph_ingest.doctype.classify import classify_jev, parse_document_type
from overgraph_ingest.doctype.evaluate import decide, summarize
from overgraph_ingest.doctype.gold import (
    DOCUMENTS,
    HARD_CASES,
    assert_gold_complete,
    assert_gold_matches_corpus,
    gold_by_path,
)
from overgraph_ingest.doctype.gold_eval import (
    refuse_doctype_run_before_gold,
    require_doctype_gold,
    review_doctype_gold,
    write_doctype_gold_baseline,
    write_doctype_gold_table,
)
from overgraph_ingest.doctype.run import run_doctype, write_doctype_run_baseline
from overgraph_ingest.doctype.store import (
    filter_documents,
    store_document_type,
    text_unit_snapshot,
)
from overgraph_ingest.doctype.taxonomy import (
    CONSULTING,
    DOCUMENT_TYPES,
    DPA,
    EMPLOYMENT,
    LEASE,
    NDA,
    OTHER,
    SUPPLY,
    TAXONOMY_VERSION,
    TERMINATION,
)
from overgraph_ingest.doctype.variant_a import classify_a
from overgraph_ingest.doctype.view import DocumentView, load_document_views
from overgraph_ingest.graph.schema import DOCUMENT
from overgraph_ingest.graph.writer import GraphWriter, open_database
from overgraph_ingest.ingest import build_parser
from overgraph_ingest.jev.client import JevResult, JevUsage
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_doctype_gold_baseline,
    load_doctype_run_baseline,
)
from overgraph_ingest.tabular.holdout import EXTRA_CORPUS
from overgraph_ingest.tabular.run import DEFAULT_DB
from tests.conftest import ingest

ROOT = Path(__file__).resolve().parents[1]


def _view(
    path: str,
    *,
    title: str,
    opening: str,
    headings: tuple[str, ...] = (),
    extra_text: str = "",
    document_id: str = "doc",
) -> DocumentView:
    return DocumentView(
        document_id=document_id,
        relative_path=path,
        title=title,
        opening=opening,
        headings=headings,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        page_count=0,
        char_count=len(opening),
        extra_text=extra_text,
    )


class ScriptJev:
    def __init__(self, choice: str = OTHER, wide_choice: str | None = None) -> None:
        self.choice = choice
        self.wide_choice = wide_choice
        self.states: list[dict[str, object]] = []
        self.calls = 0

    def ask(self, *, state, questions, model, timeout_seconds):
        self.calls += 1
        self.states.append(dict(state))
        pick = self.wide_choice if "document_text" in state and self.wide_choice else self.choice
        if callable(pick):
            pick = pick(state)
        return JevResult(
            answers={
                "document_type": {
                    "choice": pick,
                    "confidence": 0.91,
                    "distribution": {pick: 0.91},
                }
            },
            model=model,
            latency_ms=2.0,
            usage=JevUsage(prompt_tokens=10, completion_tokens=4, total_tokens=14),
            raw={},
        )


def test_gold_is_complete_before_models() -> None:
    assert_gold_complete()
    mapping = gold_by_path()
    assert len(mapping) == 100
    assert set(mapping.values()) == set(DOCUMENT_TYPES)
    assert mapping["Avtal_01_Tillsvidareanstallningsavtal.docx"] == EMPLOYMENT
    assert mapping["Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx"] == TERMINATION
    assert mapping["Avtal_06_Sekretessavtal_ensidigt_NDA.docx"] == NDA
    assert mapping["Avtal_62_PUB_GDPR_databehandlingsavtal.docx"] == DPA
    assert mapping["Avtal_05_Konsultavtal.docx"] == CONSULTING
    assert mapping["Avtal_31_Leveransavtal.docx"] == SUPPLY
    assert mapping["Avtal_17_Hyresavtal_lokal.docx"] == LEASE
    assert mapping["Avtal_92_Forlikningsavtal.docx"] == OTHER
    assert mapping["Avtal_22_Kontorshotell_coworking.docx"] == OTHER
    for case in HARD_CASES:
        assert mapping[case.left_path] != mapping[case.right_path]


def test_gold_matches_published_corpus() -> None:
    if not EXTRA_CORPUS.is_dir():
        pytest.skip("extra corpus is not checked out")
    assert_gold_matches_corpus()
    assert {path.name for path in EXTRA_CORPUS.glob("Avtal_*.docx")} == set(DOCUMENTS)


def test_a_uses_title_not_secrecy_headings() -> None:
    view = _view(
        "Avtal_01_Tillsvidareanstallningsavtal.docx",
        title="Avtal 1 – Tillsvidareanställningsavtal",
        opening="När du anställer någon utan slutdatum.",
        headings=("1. Parter", "12. Sekretess", "13. Personuppgifter"),
    )
    assert classify_a(view) == EMPLOYMENT


def test_a_does_not_call_nda_on_bare_secrecy() -> None:
    view = _view(
        "Avtal_05_Konsultavtal.docx",
        title="Avtal 5 – Konsultavtal",
        opening="När du anlitar en fristående konsult.",
        headings=("Sekretess", "Personuppgifter"),
    )
    assert classify_a(view) == CONSULTING


def test_a_keeps_hard_boundaries() -> None:
    assert classify_a(
        _view(
            "Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx",
            title="Uppsägningsbesked / överenskommelse om avslut av anställning",
            opening="När Bolaget säger upp en anställd.",
        )
    ) == TERMINATION
    assert classify_a(
        _view(
            "Avtal_22_Kontorshotell_coworking.docx",
            title="Avtal om kontorshotell/coworking",
            opening="Flexibla kontorsplatser utan lokalhyresavtal.",
        )
    ) == OTHER
    assert classify_a(
        _view(
            "Avtal_62_PUB_GDPR_databehandlingsavtal.docx",
            title="Personuppgiftsbiträdesavtal",
            opening="När DevBrains behandlar personuppgifter för kundens räkning.",
        )
    ) == DPA
    assert classify_a(
        _view(
            "Avtal_31_Leveransavtal.docx",
            title="Leveransavtal",
            opening="När ett företag säljer och levererar varor.",
        )
    ) == SUPPLY


def test_jev_b_omits_extra_text_and_c_includes_it() -> None:
    view = _view(
        "Avtal_05_Konsultavtal.docx",
        title="Konsultavtal",
        opening="Fristående uppdrag.",
        extra_text="Ytterligare brödtext om uppdraget.",
    )
    jev = ScriptJev(CONSULTING)
    narrow = classify_jev(jev, view, wide=False, model="jev-test", timeout_seconds=1)
    wide = classify_jev(jev, view, wide=True, model="jev-test", timeout_seconds=1)
    assert "document_text" not in jev.states[0]
    assert jev.states[1]["document_text"] == "Ytterligare brödtext om uppdraget."
    assert narrow.document_type == CONSULTING
    assert wide.distribution == {CONSULTING: 0.91}
    assert narrow.jev_calls == 1


def test_parse_document_type_accepts_swedish_label() -> None:
    document_type, score, distribution = parse_document_type(
        {"document_type": {"choice": "Anställningsavtal", "confidence": 0.8}}
    )
    assert document_type == EMPLOYMENT
    assert score == 0.8
    assert distribution is None


def test_store_does_not_change_text_units(ingest_paths) -> None:
    write_lettered_clause_docx(ingest_paths["input"] / "hyra.docx")
    ingest(ingest_paths)
    db = open_database(ingest_paths["db"], 8)
    try:
        writer = GraphWriter(db, batch_size=50)
        before = text_unit_snapshot(writer)
        assert before
        document = next(iter(writer.iter_nodes(DOCUMENT)))
        store_document_type(
            writer,
            document_id=str(document.key),
            document_type=LEASE,
            method="structure",
        )
        after = text_unit_snapshot(writer)
        assert after == before
        stored = writer.get_document(str(document.key))
        assert stored.props["document_type"] == LEASE
        assert stored.props["taxonomy_version"] == TAXONOMY_VERSION
        assert "hyra.docx" in filter_documents(writer, LEASE)
        assert filter_documents(writer, NDA) == []
    finally:
        db.close()


def test_run_compares_a_b_c_without_touching_phase2(tmp_path: Path) -> None:
    views = [
        _view(
            "Avtal_01_Tillsvidareanstallningsavtal.docx",
            title="Tillsvidareanställningsavtal",
            opening="Anställning utan slutdatum.",
            extra_text="Lön och semester.",
            document_id="emp",
        ),
        _view(
            "Avtal_06_Sekretessavtal_ensidigt_NDA.docx",
            title="Sekretessavtal ensidigt (NDA)",
            opening="Bara den ena parten lämnar ut information.",
            extra_text="Konfidentiell information.",
            document_id="nda",
        ),
        _view(
            "Avtal_36_Underleverantorsavtal.docx",
            title="Underleverantörsavtal",
            opening="Utföra en del av ett uppdrag.",
            extra_text="Utveckla och testa integrationen.",
            document_id="sub",
        ),
    ]
    gold = write_doctype_gold_baseline(review_doctype_gold(), tmp_path / "gold.json")
    jev = ScriptJev(
        choice=lambda state: (
            CONSULTING if "Underleverantörsavtal" in str(state.get("title")) else classify_a(
                _view(
                    "x.docx",
                    title=str(state.get("title") or ""),
                    opening=str(state.get("opening") or ""),
                )
            )
        )
    )
    payload = run_doctype(
        views=views,
        jev=jev,
        gold_path=gold,
        store_db_path=tmp_path / "filter",
        require_gold=True,
    )
    assert payload["does_not_change_text_units"] is True
    assert payload["does_not_change_answer_cell"] is True
    assert payload["no_production_integration"] is True
    assert payload["store"]["text_units_unchanged"] is True
    assert payload["variants"]["A"]["summary"]["correct"] == 2
    assert payload["variants"]["B"]["summary"]["correct"] == 3
    assert payload["decision"]["jev_adds_measurable_quality"] is True
    assert jev.calls == 6
    write_doctype_run_baseline(payload, tmp_path / "run.json")
    with pytest.raises(FileExistsError):
        write_doctype_run_baseline(payload, tmp_path / "run.json")


def test_gold_freeze_refuses_jev_and_overwrite(tmp_path: Path) -> None:
    payload = review_doctype_gold()
    assert payload["does_not_run_jev"] is True
    assert payload["models_not_run"] is True
    assert payload["headline"]["documents"] == 100
    path = write_doctype_gold_baseline(payload, tmp_path / "gold.json")
    write_doctype_gold_table(payload, tmp_path)
    with pytest.raises(FileExistsError):
        write_doctype_gold_baseline(payload, path)
    with pytest.raises(RuntimeError, match="not frozen"):
        require_doctype_gold(tmp_path / "missing.json")
    with pytest.raises(RuntimeError, match="not frozen"):
        refuse_doctype_run_before_gold()


def test_db_is_closed_before_jev(ingest_paths) -> None:
    write_lettered_clause_docx(ingest_paths["input"] / "Avtal_01_Tillsvidareanstallningsavtal.docx")
    ingest(ingest_paths)
    views = load_document_views(db_path=ingest_paths["db"], dense_dimension=8)
    assert views
    started = threading.Event()
    opened: list[bool] = []

    def other_client() -> None:
        started.wait(2)
        db = open_database(ingest_paths["db"], 8)
        try:
            opened.append(True)
        finally:
            db.close()

    class SlowJev(ScriptJev):
        def ask(self, *, state, questions, model, timeout_seconds):
            started.set()
            time.sleep(0.2)
            return super().ask(
                state=state,
                questions=questions,
                model=model,
                timeout_seconds=timeout_seconds,
            )

    thread = threading.Thread(target=other_client)
    thread.start()
    classify_jev(SlowJev(OTHER), views[0], wide=False, model="jev-test", timeout_seconds=1)
    thread.join()
    assert opened == [True]


def test_cli_flags_and_conclusions() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["--db", "data/extra-overgraph-phase2", "--doctype-gold"]
    )
    assert args.doctype_gold is True
    args = parser.parse_args(
        ["--db", "data/extra-overgraph-phase2", "--doctype-run"]
    )
    assert args.doctype_run is True
    assert RETRIEVAL_CONCLUSIONS["doctype_classification"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["doctype_does_not_change_text_units"] is True
    assert RETRIEVAL_CONCLUSIONS["doctype_does_not_change_answer_cell"] is True
    assert RETRIEVAL_CONCLUSIONS["doctype_no_production_integration"] is True
    assert RETRIEVAL_CONCLUSIONS["doctype_models_not_run"] is False
    assert RETRIEVAL_CONCLUSIONS["doctype_best_variant"] == "B"
    assert RETRIEVAL_CONCLUSIONS["doctype_jev_adds_measurable_quality"] is True
    assert RETRIEVAL_CONCLUSIONS["doctype_wider_context_improves"] is False
    assert RETRIEVAL_CONCLUSIONS["tabular_default_remains_d"] is True


def test_frozen_doctype_baselines() -> None:
    gold = load_doctype_gold_baseline()
    assert gold["does_not_run_jev"] is True
    assert gold["headline"]["documents"] == 100
    run = load_doctype_run_baseline()
    assert run["does_not_change_text_units"] is True
    assert run["does_not_change_answer_cell"] is True
    assert run["store"]["text_units_unchanged"] is True
    assert run["variants"]["A"]["correct"] == 81
    assert run["variants"]["B"]["correct"] == 86
    assert run["variants"]["C"]["correct"] == 84
    assert run["decision"]["best_variant"] == "B"
    assert run["decision"]["no_quality_threshold"] is True
    assert run["jev_calls"] == 200
    with pytest.raises(FileExistsError):
        write_doctype_gold_baseline(review_doctype_gold(), ROOT / "baselines" / "phase2-doctype-gold-v1.json")


def test_summarize_and_decide_have_no_threshold() -> None:
    rows = [
        {"predicted": EMPLOYMENT, "gold": EMPLOYMENT, "correct": True, "relative_path": "a"},
        {"predicted": NDA, "gold": EMPLOYMENT, "correct": False, "relative_path": "b"},
    ]
    summary = summarize(rows)
    assert summary["correct"] == 1
    assert summary["accuracy"] == 0.5
    assert summary["per_type"][EMPLOYMENT]["recall"] == 0.5
    decision = decide({"A": summary, "B": {"accuracy": 1.0, "correct": 2}}, {})
    assert decision["no_quality_threshold"] is True
    assert decision["jev_adds_measurable_quality"] is True


def test_a_scores_published_views_without_jev() -> None:
    if not DEFAULT_DB.is_dir():
        pytest.skip("phase2 catalog is not checked out")
    views = load_document_views(db_path=DEFAULT_DB, dense_dimension=3072)
    assert len(views) == 100
    mapping = gold_by_path()
    scored = [classify_a(view) == mapping[view.relative_path] for view in views]
    assert sum(1 for view in views if view.extra_text) >= 1
    assert any(not view.extra_text or "document_text" not in view.a_state() for view in views)
    assert 0 <= sum(scored) <= 100

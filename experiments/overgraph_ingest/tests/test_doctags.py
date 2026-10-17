from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from overgraph_ingest.doctags.catalog import (
    CONFIDENTIALITY,
    EMPLOYMENT_TYPE,
    PERMANENT,
    PROBATIONARY,
    SECRECY,
)
from overgraph_ingest.doctags.classification import (
    classification_record,
    load_frozen_classifications,
)
from overgraph_ingest.doctags.context import TagDocument, load_tag_documents
from overgraph_ingest.doctags.evaluate import summarize
from overgraph_ingest.doctags.extract import extract_b
from overgraph_ingest.doctags.gold import DOCUMENTS, TAG_GOLDS, assert_tag_gold_complete
from overgraph_ingest.doctags.gold_eval import (
    refuse_document_tags_run_before_gold,
    require_document_tags_gold,
    review_document_tags_gold,
    write_document_tags_gold_baseline,
    write_document_tags_gold_table,
)
from overgraph_ingest.doctags.run import run_document_tags, write_document_tags_run_baseline
from overgraph_ingest.doctags.schema import REJECTED, TAG
from overgraph_ingest.doctags.source import validate_source
from overgraph_ingest.doctags.store import (
    add_user_tag,
    correct_effective_type,
    filter_documents,
    persist_proposals,
    reject_tag,
    store_classification,
    store_tag,
)
from overgraph_ingest.doctags.variant_a import extract_a
from overgraph_ingest.graph.writer import GraphWriter, open_database
from overgraph_ingest.ingest import build_parser
from overgraph_ingest.jev.client import JevResult, JevUsage
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_doctype_run_baseline,
    load_document_tags_gold_baseline,
    load_document_tags_run_baseline,
)
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.tabular.run import DEFAULT_DB

ROOT = Path(__file__).resolve().parents[1]


def _unit(
    text: str,
    *,
    key: str = "unit-1",
    document_id: str = "doc-1",
    relative_path: str = "Avtal_01_Tillsvidareanstallningsavtal.docx",
    char_start: int = 0,
) -> StoredUnit:
    return StoredUnit(
        node_id=1,
        key=key,
        document_id=document_id,
        relative_path=relative_path,
        text=text,
        dense=None,
        sparse=None,
        sequence=1,
        char_start=char_start,
        char_end=char_start + len(text),
    )


class TagJev:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {"employment_type": PERMANENT}
        self.calls = 0
        self.states: list[dict[str, object]] = []
        self.questions: list[dict[str, object]] = []

    def ask(self, *, state, questions, model, timeout_seconds):
        self.calls += 1
        self.states.append(dict(state))
        self.questions.append(questions)
        answers = {}
        excerpt = "none"
        for spec in questions.values():
            listed = [key for key in spec["criteria"] if key != "none"]
            if listed and excerpt == "none":
                excerpt = listed[0]
        for key, spec in questions.items():
            if key.endswith("_value_1"):
                tag_class = key[: -len("_value_1")]
                choice = self.values.get(tag_class, "none")
                answers[key] = {
                    "choice": choice,
                    "confidence": 0.88,
                    "probabilities": {choice: 0.88, "none": 0.12},
                }
            elif key.endswith("_excerpt_1") and self.values.get(key[: -len("_excerpt_1")], "none") != "none":
                answers[key] = {"choice": excerpt if excerpt in spec["criteria"] else "none"}
            else:
                answers[key] = {"choice": "none", "confidence": 0.1}
        return JevResult(
            answers=answers,
            model=model,
            latency_ms=3.0,
            usage=JevUsage(prompt_tokens=12, completion_tokens=6, total_tokens=18),
            raw={},
        )


def test_gold_is_locked_before_models() -> None:
    assert_tag_gold_complete()
    assert len(DOCUMENTS) == 16
    assert len(TAG_GOLDS) == 34
    assert any(item.value == PROBATIONARY for item in TAG_GOLDS)
    assert sum(1 for item in TAG_GOLDS if item.relative_path.endswith("Avtal_02_Provanstallningsavtal.docx") and item.tag_class == EMPLOYMENT_TYPE) == 2
    assert not any(item.relative_path.endswith("Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx") for item in TAG_GOLDS)


def test_frozen_doctype_b_is_reused_not_rerun() -> None:
    rows = load_frozen_classifications()
    assert set(rows) == set(DOCUMENTS)
    first = classification_record(rows["Avtal_01_Tillsvidareanstallningsavtal.docx"])
    assert first["predicted_type"] == "employment_agreement"
    assert first["confidence"] == 1.0
    assert first["probabilities"]["employment_agreement"] == 1.0
    assert first["model"] == "jev-1.13.0"
    frozen = load_doctype_run_baseline()
    assert frozen["variants"]["B"]["correct"] == 86
    assert frozen["do_not_overwrite"] is True


def test_a_extracts_multiple_employment_types() -> None:
    units = [
        _unit(
            "Anställningen inleds som Provanställning och övergår sedan till tillsvidareanställning.",
            relative_path="Avtal_02_Provanstallningsavtal.docx",
        )
    ]
    rows = extract_a(
        relative_path="Avtal_02_Provanstallningsavtal.docx",
        document_id="doc-1",
        units=units,
    )
    values = {(row["tag_class"], row["value"]) for row in rows}
    assert (EMPLOYMENT_TYPE, PROBATIONARY) in values
    assert (EMPLOYMENT_TYPE, PERMANENT) in values
    assert rows[0]["source"]["validated"] is True


def test_source_requires_exact_excerpt() -> None:
    unit = _unit("Avtalet kan sägas upp med tre månaders uppsägningstid.")
    ok = validate_source(
        "Avtalet kan sägas upp med tre månaders uppsägningstid.",
        unit=unit,
        document_id="doc-1",
    )
    bad = validate_source("påhittad text", unit=unit, document_id="doc-1")
    other = validate_source(unit.text, unit=unit, document_id="other")
    assert ok.validated is True
    assert ok.start == 0
    assert bad.validated is False
    assert other.validated is False


def test_jev_b_is_one_call_and_keeps_raw_confidence() -> None:
    unit = _unit("Detta är en tillsvidareanställning med tystnadsplikt.")
    jev = TagJev({EMPLOYMENT_TYPE: PERMANENT, CONFIDENTIALITY: SECRECY})
    rows, latency_ms, calls, model = extract_b(
        jev,
        relative_path="Avtal_01_Tillsvidareanstallningsavtal.docx",
        document_id="doc-1",
        document_type="employment_agreement",
        title="Tillsvidareanställningsavtal",
        opening="Anställning utan slutdatum.",
        units=[unit],
        model="jev-test",
        timeout_seconds=1,
    )
    assert calls == 1
    assert jev.calls == 1
    assert "document_type" in jev.states[0]
    assert jev.states[0]["tag_classes"]
    assert any(row["confidence"] == 0.88 for row in rows)
    assert any(row["probabilities"][PERMANENT] == 0.88 for row in rows if row["value"] == PERMANENT)
    assert latency_ms == 3.0
    assert model == "jev-test"


def test_store_corrections_survive_reclassify(tmp_path: Path) -> None:
    db = open_database(tmp_path / "tags", 8)
    try:
        writer = GraphWriter(db, batch_size=50)
        store_classification(
            writer,
            document_id="doc-1",
            predicted_type="employment_agreement",
            confidence=0.41,
            probabilities={"employment_agreement": 0.41, "other": 0.59},
            model="jev-1.13.0",
            taxonomy_version="document-types-v1",
            tenant_id="t1",
            workspace_id="w1",
            extra_props={"relative_path": "Avtal_01_Tillsvidareanstallningsavtal.docx", "document_id": "doc-1"},
        )
        stored = writer.get_document("doc-1")
        assert stored.props["classification_confidence"] == 0.41
        assert json.loads(stored.props["classification_probabilities"])["employment_agreement"] == 0.41
        correct_effective_type(writer, document_id="doc-1", effective_type="consulting_agreement")
        store_classification(
            writer,
            document_id="doc-1",
            predicted_type="employment_agreement",
            confidence=0.99,
            probabilities={"employment_agreement": 0.99},
            model="jev-1.13.0",
            taxonomy_version="document-types-v1",
            tenant_id="t1",
            workspace_id="w1",
        )
        again = writer.get_document("doc-1")
        assert again.props["effective_type"] == "consulting_agreement"
        assert again.props["predicted_type"] == "employment_agreement"
        assert again.props["classification_confidence"] == 0.99
        tag = store_tag(
            writer,
            document_id="doc-1",
            relative_path="Avtal_01_Tillsvidareanstallningsavtal.docx",
            tag_class=EMPLOYMENT_TYPE,
            value=PERMANENT,
            origin="jev",
            tenant_id="t1",
            workspace_id="w1",
            confidence=0.7,
        )
        reject_tag(writer, tag["tag_id"])
        assert store_tag(
            writer,
            document_id="doc-1",
            relative_path="Avtal_01_Tillsvidareanstallningsavtal.docx",
            tag_class=EMPLOYMENT_TYPE,
            value=PERMANENT,
            origin="jev",
            tenant_id="t1",
            workspace_id="w1",
        ) is None
        add_user_tag(
            writer,
            document_id="doc-1",
            relative_path="Avtal_01_Tillsvidareanstallningsavtal.docx",
            tag_class="user_label",
            value="important_customer",
            tenant_id="t1",
            workspace_id="w1",
            display_value="Viktig kund",
        )
        persist_proposals(
            writer,
            [
                {
                    "document_id": "doc-1",
                    "relative_path": "Avtal_01_Tillsvidareanstallningsavtal.docx",
                    "tag_class": "user_label",
                    "value": "important_customer",
                    "origin": "jev",
                }
            ],
            tenant_id="t1",
            workspace_id="w1",
        )
        assert "Avtal_01_Tillsvidareanstallningsavtal.docx" in filter_documents(
            writer,
            tenant_id="t1",
            workspace_id="w1",
            tag_class="user_label",
            tag_value="important_customer",
        )
        assert filter_documents(
            writer,
            tenant_id="other",
            workspace_id="w1",
            tag_class="user_label",
            tag_value="important_customer",
        ) == []
        node = writer.get_node(TAG, tag["tag_id"])
        assert node.props["review_status"] == REJECTED
    finally:
        db.close()


def test_run_compares_a_and_b_without_touching_frozen_doctype(tmp_path: Path) -> None:
    gold = write_document_tags_gold_baseline(review_document_tags_gold(), tmp_path / "gold.json")
    documents = [
        TagDocument(
            document_id="70f30ce1ad30de0be6cefeedfeb537d03fbd6cb92dcd9eec39cd849d1a536ddd",
            relative_path="Avtal_01_Tillsvidareanstallningsavtal.docx",
            units=(
                _unit(
                    "Detta är en tillsvidareanställning. Uppsägningstiden är en (1) månad. "
                    "Arbetstagaren ska hålla konfidentiell information hemlig.",
                    document_id="70f30ce1ad30de0be6cefeedfeb537d03fbd6cb92dcd9eec39cd849d1a536ddd",
                ),
            ),
        )
    ]
    payload = run_document_tags(
        documents=documents,
        jev=TagJev({EMPLOYMENT_TYPE: PERMANENT, CONFIDENTIALITY: SECRECY}),
        gold_path=gold,
        store_db_path=tmp_path / "filter",
        require_gold=True,
    )
    assert payload["does_not_change_answer_cell"] is True
    assert payload["does_not_change_doctype_baseline"] is True
    assert payload["reuses_frozen_doctype_b"] is True
    assert payload["does_not_rerun_doctype_jev"] is True
    assert payload["no_automatic_approval_threshold"] is True
    assert payload["store"]["type_correction_survives_reclassify"] is True
    assert payload["store"]["tenant_isolation"] is True
    assert payload["cost"]["jev_calls_per_document"]["B"] == 1.0
    write_document_tags_run_baseline(payload, tmp_path / "run.json")
    with pytest.raises(FileExistsError):
        write_document_tags_run_baseline(payload, tmp_path / "run.json")


def test_gold_freeze_refuses_jev_and_overwrite(tmp_path: Path) -> None:
    payload = review_document_tags_gold()
    assert payload["does_not_run_jev"] is True
    assert payload["inventory"]["socialism_has_document_tag_model"] is False
    path = write_document_tags_gold_baseline(payload, tmp_path / "gold.json")
    write_document_tags_gold_table(payload, tmp_path)
    with pytest.raises(FileExistsError):
        write_document_tags_gold_baseline(payload, path)
    with pytest.raises(RuntimeError, match="not frozen"):
        require_document_tags_gold(tmp_path / "missing.json")
    with pytest.raises(RuntimeError, match="not frozen"):
        refuse_document_tags_run_before_gold()


def test_db_is_closed_before_jev() -> None:
    if not DEFAULT_DB.is_dir():
        pytest.skip("phase2 catalog is not checked out")
    documents = load_tag_documents(db_path=DEFAULT_DB, dense_dimension=3072)
    assert documents
    started = threading.Event()
    opened: list[bool] = []

    def other_client() -> None:
        started.wait(2)
        db = open_database(DEFAULT_DB, 3072)
        try:
            opened.append(True)
        finally:
            db.close()

    class SlowJev(TagJev):
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
    extract_b(
        SlowJev(),
        relative_path=documents[0].relative_path,
        document_id=documents[0].document_id,
        document_type="employment_agreement",
        title="x",
        opening="y",
        units=list(documents[0].units),
        model="jev-test",
        timeout_seconds=1,
    )
    thread.join()
    assert opened == [True]


def test_cli_flags_and_conclusions() -> None:
    parser = build_parser()
    args = parser.parse_args(["--db", "data/extra-overgraph-phase2", "--document-tags-gold"])
    assert args.document_tags_gold is True
    args = parser.parse_args(["--db", "data/extra-overgraph-phase2", "--document-tags-run"])
    assert args.document_tags_run is True
    assert RETRIEVAL_CONCLUSIONS["document_tags"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["document_tags_does_not_change_answer_cell"] is True
    assert RETRIEVAL_CONCLUSIONS["document_tags_does_not_change_doctype_baseline"] is True
    assert RETRIEVAL_CONCLUSIONS["document_tags_reuses_frozen_doctype_b"] is True
    assert RETRIEVAL_CONCLUSIONS["document_tags_no_automatic_approval_threshold"] is True
    assert RETRIEVAL_CONCLUSIONS["document_tags_best_variant"] == "A"
    assert RETRIEVAL_CONCLUSIONS["document_tags_a_is_cheap_ingest_candidate"] is True
    assert RETRIEVAL_CONCLUSIONS["document_tags_b_is_experimental_semantic_alternative"] is True
    assert RETRIEVAL_CONCLUSIONS["document_tags_automatic_tags_are_proposals"] is True
    assert RETRIEVAL_CONCLUSIONS["document_tags_jev_adds_measurable_quality"] is False
    assert RETRIEVAL_CONCLUSIONS["doctype_best_variant"] == "B"
    assert RETRIEVAL_CONCLUSIONS["tabular_default_remains_d"] is True


def test_frozen_document_tags_baselines() -> None:
    gold = load_document_tags_gold_baseline()
    assert gold["does_not_run_jev"] is True
    assert gold["headline"]["documents"] == 16
    assert gold["headline"]["tags"] == 34
    assert gold["inventory"]["socialism_has_document_tag_model"] is False
    run = load_document_tags_run_baseline()
    assert run["does_not_change_text_units"] is True
    assert run["does_not_change_answer_cell"] is True
    assert run["does_not_change_doctype_baseline"] is True
    assert run["reuses_frozen_doctype_b"] is True
    assert run["variants"]["A"]["hits"] == 32
    assert run["variants"]["B"]["hits"] == 32
    assert run["variants"]["A"]["extras"] == 5
    assert run["variants"]["B"]["extras"] == 3
    assert run["jev_calls"] == 16
    assert run["store"]["type_correction_survives_reclassify"] is True
    assert run["store"]["rejected_tag_stays_rejected"] is True
    assert run["store"]["tenant_isolation"] is True
    assert run["decision"]["no_quality_threshold"] is True
    with pytest.raises(FileExistsError):
        write_document_tags_gold_baseline(
            review_document_tags_gold(),
            ROOT / "baselines" / "phase2-document-tags-gold-v1.json",
        )
    with pytest.raises(FileExistsError):
        write_document_tags_run_baseline(
            run,
            ROOT / "baselines" / "phase2-document-tags-v1.json",
        )


def test_summarize_has_no_threshold() -> None:
    summary = summarize(
        [
            {
                "relative_path": "Avtal_01_Tillsvidareanstallningsavtal.docx",
                "tag_class": EMPLOYMENT_TYPE,
                "value": PERMANENT,
                "source": {"excerpt": "tillsvidareanställning", "validated": True},
                "confidence": 0.4,
            }
        ]
    )
    assert summary["hits"] == 1
    assert summary["confidence"]["not_used_as_threshold"] is True
    assert summary["source"]["position_is_not_legal_proof"] is True

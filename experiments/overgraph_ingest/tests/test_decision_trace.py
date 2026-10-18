from pathlib import Path

from overgraph_ingest.coverage.decision_trace import (
    contrast_cases,
    inspect_saved_run,
    traces_for_found,
    trace_document,
)
from overgraph_ingest.coverage.state import NEEDS_ANALYSIS
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.coverage.decision_trace_run import (
    TRACE_BASELINE_ID,
    freeze_decision_trace_baseline,
    run_decision_trace,
)
from overgraph_ingest.coverage.proof import COMPOSITE
from overgraph_ingest.coverage.state import EVIDENCE_FOUND, DocumentState, UnitRecord
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_decision_trace_baseline,
)


def _found_doc(*, path: str, yes_text: str, hop_text: str | None = None) -> DocumentState:
    rows = [
        UnitRecord(key=f"{path}:yes", predicted="YES", source="global", text=yes_text),
    ]
    if hop_text is not None:
        rows.append(
            UnitRecord(
                key=f"{path}:hop",
                predicted="NO",
                source="hop:SAME_SECTION",
                hop="hop:SAME_SECTION",
                text=hop_text,
            )
        )
    return DocumentState(
        relative_path=path,
        document_units=4,
        retrieved=rows,
        status=EVIDENCE_FOUND,
        hop_attempted=hop_text is not None,
    )


def test_trace_records_units_and_does_not_guess_error_class() -> None:
    doc = _found_doc(
        path="avtal_x.docx",
        yes_text="Begränsningarna enligt ovan gäller inte om part har orsakat skadan uppsåtligen.",
        hop_text="Parterna har tystnadsplikt.",
    )
    row = trace_document(
        doc,
        query="sekretessundantag",
        gold_id="E",
        proof_kind=COMPOSITE,
        relevant=False,
    )
    assert row["document_id"] == "avtal_x.docx"
    assert row["query"] == "sekretessundantag"
    assert row["jev_yes_units"][0]["text"].startswith("Begränsningarna")
    assert row["events"][0]["kind"] == "classify"
    assert row["events"][1]["kind"] == "navigation"
    assert row["events"][-1]["kind"] == "proof_decision"
    assert row["evidence_found_before_navigation"] is False
    assert row["navigation_added_necessary_complete"] is True
    assert row["jev_yes_units"][0]["identity"]["key"].endswith(":yes")
    assert row["jev_yes_units"][0]["identity"]["text_sha256"]
    assert row["hops"][0]["hop"] == "hop:SAME_SECTION"
    assert len(row["units_used"]) == 2
    assert row["why_evidence_found"] == "jev_yes_after_hop"
    assert row["required_source_span"] is None
    assert row["error_class"] == "unobserved"
    assert row["link_re_matches"] is False
    assert row["role"] == "false_complete"


def test_true_complete_without_link_re_is_a_contrast_case() -> None:
    doc = _found_doc(
        path="avtal_103.docx",
        yes_text="Inget i denna punkt ska begränsa parts ansvar för brott mot avsnitt 4.",
    )
    row = trace_document(
        doc,
        query="sekretessundantag",
        gold_id="E",
        proof_kind=COMPOSITE,
        relevant=True,
        gold_span="Inget i denna punkt ska begränsa parts ansvar för brott mot avsnitt 4.",
    )
    assert row["role"] == "true_complete"
    assert row["link_re_matches"] is False
    assert row["why_evidence_found"] == "jev_yes_without_pending_hop"
    assert row["required_source_span"].startswith("Inget i denna punkt")
    contrast = contrast_cases([row])
    assert contrast["observed_true_complete_missed_count"] == 1
    assert contrast["observed_false_complete_count"] == 0
    assert contrast["do_not_pad_with_hypotheses"] is True


def test_avtal_60_style_relation_exists_before_required_hop() -> None:
    doc = _found_doc(
        path="Avtal_60_Pilotavtal_PoC.docx",
        yes_text="Begränsningarna gäller inte vid uppsåt, grov vårdslöshet eller brott mot sekretessåtagandet.",
        hop_text="Sekretessåtagandet står i punkt 8.",
    )
    row = trace_document(
        doc,
        query="sekretessundantag",
        gold_id="E",
        proof_kind=COMPOSITE,
        relevant=True,
        gold_span="brott mot sekretessåtagandet",
    )
    assert row["controller_status_before_navigation"] == NEEDS_ANALYSIS
    assert row["evidence_found_before_navigation"] is False
    assert row["link_re_matches_before_navigation"] is True
    assert row["navigation_added_necessary_complete"] is True
    assert row["status"] == EVIDENCE_FOUND


def test_uncertain_complete_is_not_false_complete() -> None:
    doc = _found_doc(
        path="avtal_138.docx",
        yes_text="Begränsningen gäller inte heller vid brott mot sekretessåtagandet i punkt 12.",
    )
    row = trace_document(
        doc,
        query="sekretessundantag",
        gold_id="E",
        proof_kind=COMPOSITE,
        relevant=False,
        gold_classification="UNCERTAIN",
    )
    assert row["role"] == "complete_uncertain"
    assert row["error_class"] is None
    contrast = contrast_cases([row])
    assert contrast["observed_false_complete_count"] == 0
    assert contrast["complete_uncertain_count"] == 1


def test_trace_uses_stable_unit_identity() -> None:
    unit = StoredUnit(
        42,
        "unit-key",
        "doc-1",
        "avtal_103.docx",
        "Inget i denna punkt ska begränsa parts ansvar för brott mot avsnitt 4.",
        None,
        None,
        "struct-1",
        3,
        10,
        80,
        "hash-1",
    )
    doc = DocumentState(
        relative_path="avtal_103.docx",
        document_units=2,
        retrieved=[
            UnitRecord(key="unit-key", predicted="YES", source="global", text=unit.text),
        ],
        status=EVIDENCE_FOUND,
    )
    row = trace_document(
        doc,
        query="q",
        gold_id="E",
        proof_kind=COMPOSITE,
        relevant=True,
        units_by_key={"unit-key": unit},
    )
    identity = row["events"][0]["identity"]
    assert identity["node_id"] == 42
    assert identity["key"] == "unit-key"
    assert identity["char_start"] == 10
    assert identity["char_end"] == 80
    assert identity["content_hash"] == "hash-1"
    assert identity["text_sha256"]


def test_tracing_does_not_change_controller_status() -> None:
    doc = _found_doc(
        path="avtal_x.docx",
        yes_text="Begränsningarna enligt ovan gäller inte om part har orsakat skadan uppsåtligen.",
        hop_text="Parterna har tystnadsplikt.",
    )
    before = doc.status
    traces_for_found(
        {"avtal_x.docx": doc},
        RetrievalGold(
            id="E",
            query="q",
            relevant_units=[],
            hard_negatives=[],
            proof_kind=COMPOSITE,
        ),
    )
    assert doc.status == before == EVIDENCE_FOUND


def test_inspect_reads_traces_from_budget() -> None:
    found = inspect_saved_run(
        {
            "golds": [
                {
                    "budgets": [
                        {
                            "budget": 5,
                            "decision_traces": [
                                {
                                    "role": "false_complete",
                                    "link_re_matches": False,
                                }
                            ],
                        }
                    ]
                }
            ]
        }
    )
    assert found["observability_gap"] is False
    assert found["contrast"]["observed_false_complete_count"] == 1


def test_saved_run_without_unit_traces_is_an_observability_gap() -> None:
    gap = inspect_saved_run(
        {
            "golds": [
                {
                    "budgets": [
                        {
                            "budget": 5,
                            "evidence_found_nonrelevant": ["named-only.docx"],
                        }
                    ]
                }
            ]
        }
    )
    assert gap["observability_gap"] is True
    assert gap["named_paths_without_units"] == ["named-only.docx"]
    assert gap["cannot_read_jev_yes_unit"] is True
    assert gap["do_not_guess_documents"] is True


def test_decision_trace_v1_freeze_still_records_the_gap() -> None:
    frozen = load_decision_trace_baseline()
    assert frozen["id"] == TRACE_BASELINE_ID
    assert frozen["headline"]["observability_gap"] is True
    assert frozen["headline"]["do_not_guess_documents"] is True
    assert Path("baselines/phase2-decision-trace-v1.json").is_file()
    assert freeze_decision_trace_baseline(run_decision_trace())["no_link_re_change"] is True


def test_observed_blind_traces_do_not_pad_false_completes() -> None:
    from overgraph_ingest.retrieval.conclusions import load_blind_trace_run_baseline

    frozen = load_blind_trace_run_baseline()
    assert frozen["headline"]["observed_false_complete_count"] == 2
    assert frozen["headline"]["complete_uncertain_count"] == 3
    assert frozen["uncertain_is_not_false_complete"] is True
    assert frozen["do_not_pad_false_completes"] is True
    assert frozen["no_new_proof_rule"] is True
    assert [row["document_id"] for row in frozen["false_complete"]] == [
        "avtal_119.docx",
        "avtal_200.docx",
    ]
    assert RETRIEVAL_CONCLUSIONS["decision_traces_observed"] is True
    assert RETRIEVAL_CONCLUSIONS["uncertain_is_not_false_complete"] is True
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"

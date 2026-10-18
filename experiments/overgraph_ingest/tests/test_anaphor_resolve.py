from overgraph_ingest.coverage.anaphor_resolve import (
    RESOLVED_ANAPHOR,
    RESOLVED_LIST,
    assess_with_anaphors,
)
from overgraph_ingest.coverage.anaphor_run import (
    freeze_ability_curve_baseline,
    freeze_anaphor_baseline,
    run_anaphor_resolve,
)
from overgraph_ingest.coverage.chain_contract import SUPPORTED, UNDECIDED
from overgraph_ingest.coverage.clause_resolve import RESOLVED_AND_RELATED
from overgraph_ingest.coverage.stop_replay import INVESTIGATION_PARTIAL
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_ability_curve_baseline,
    load_anaphor_list_baseline,
)
from tests.test_clause_resolve import CATALOG_103, CATALOG_138
from tests.test_decision_contract import (
    HOP_107,
    YES_103,
    YES_106,
    YES_107,
    YES_140,
    _trace,
)


def _seq_trace(document_id: str, events: list[tuple[str, str, str, int]]) -> dict[str, object]:
    rows = []
    for index, (kind, predicted, text, sequence) in enumerate(events):
        rows.append(
            {
                "index": index,
                "kind": kind,
                "predicted": predicted,
                "text": text,
                "hop": "hop:PREVIOUS" if kind == "navigation" else None,
                "identity": {"key": f"{document_id}-{index}", "sequence": sequence},
            }
        )
    rows.append({"index": len(rows), "kind": "proof_decision", "status": "EVIDENCE_FOUND"})
    return {
        "document_id": document_id,
        "events": rows,
        "status": "EVIDENCE_FOUND",
        "why_evidence_found": "jev_yes_after_hop",
    }


def test_106_uses_previous_sentence_not_dataskydd_hop() -> None:
    judged = assess_with_anaphors(_trace("avtal_106.docx", [("classify", "YES", YES_106)]), [])
    assert judged["examined_support"] == SUPPORTED
    assert judged["why"] == RESOLVED_ANAPHOR
    assert judged["discourse_link"]["how"] == "previous_sentence_in_unit"
    assert "tystnadsplikt" in judged["discourse_link"]["anaphor"]
    assert "ska inte tillämpas" in judged["discourse_link"]["antecedent"]
    assert judged["does_not_concatenate_units"] is True
    assert judged["investigation"] == INVESTIGATION_PARTIAL


def test_107_anchors_to_previous_predication() -> None:
    judged = assess_with_anaphors(
        _seq_trace(
            "avtal_107.docx",
            [
                ("classify", "NO", "3. Sekretess och tystnadsplikt\n", 10),
                ("classify", "YES", YES_107, 22),
                ("navigation", "NO", HOP_107, 21),
            ],
        ),
        [],
    )
    assert judged["examined_support"] == SUPPORTED
    assert judged["why"] == RESOLVED_ANAPHOR
    assert judged["discourse_link"]["how"] == "previous_unit_predication"
    assert "ska inte tillämpas" in judged["discourse_link"]["antecedent"]
    assert judged["finding_antecedent_is_not_admission"] is True


def test_secrecy_heading_is_not_the_antecedent() -> None:
    judged = assess_with_anaphors(
        _seq_trace(
            "avtal_107.docx",
            [
                ("classify", "YES", YES_107, 22),
                ("navigation", "NO", "3. Sekretess och tystnadsplikt\n", 21),
            ],
        ),
        [],
    )
    assert judged["examined_support"] == UNDECIDED
    assert judged["discourse_link"]["holds"] is False


def test_140_uses_list_intro_not_joined_text() -> None:
    judged = assess_with_anaphors(_trace("avtal_140.docx", [("classify", "YES", YES_140)]), [])
    assert judged["examined_support"] == SUPPORTED
    assert judged["why"] == RESOLVED_LIST
    assert judged["discourse_link"]["how"] == "list_intro_to_item"
    assert "gäller inte i följande fall" in judged["discourse_link"]["intro"]


def test_secrecy_exception_list_is_not_the_claim() -> None:
    judged = assess_with_anaphors(
        _trace(
            "avtal_118.docx",
            [
                (
                    "classify",
                    "NO",
                    "4.3\tSkyldigheten att iaktta sekretess gäller inte information som part kan visa\n"
                    "(a) är eller blir allmänt tillgänglig;\n",
                ),
                (
                    "classify",
                    "YES",
                    "5.4\tInget i denna punkt ska begränsa parts ansvar för brott mot artikel 4.\n",
                ),
            ],
        ),
        [],
    )
    assert judged["examined_support"] == UNDECIDED
    assert judged.get("discourse_link") is None


def test_clause_and_conflict_controls_remain() -> None:
    assert (
        assess_with_anaphors(
            _trace("avtal_103.docx", [("classify", "YES", YES_103)]),
            CATALOG_103,
        )["why"]
        == RESOLVED_AND_RELATED
    )
    judged = assess_with_anaphors(
        _trace("avtal_138.docx", [("classify", "YES", "Begränsningen gäller inte heller vid brott mot sekretessåtagandet i punkt 12.\n")]),
        CATALOG_138,
    )
    assert judged["examined_support"] == UNDECIDED


def test_anaphor_and_curve_baselines() -> None:
    frozen = load_anaphor_list_baseline()
    assert frozen["headline"]["treatment_counts"]["false_approvals"] == 0
    assert frozen["headline"]["delta"]["true_support"] == 4
    assert frozen["headline"]["cases"]["avtal_107.docx"]["why"] == RESOLVED_ANAPHOR
    assert frozen["headline"]["cases"]["avtal_140.docx"]["why"] == RESOLVED_LIST
    curve = load_ability_curve_baseline()["headline"]["curve"]
    assert [row["experiment"] for row in curve] == [
        "hop-always",
        "grounded-chain",
        "clause-resolve",
        "anaphor-list",
    ]
    assert curve[0]["note"] == "gold_document_outcomes_not_verified_proofs"
    assert curve[-1]["true_support"] == 19
    assert curve[-1]["false_approvals"] == 0
    assert RETRIEVAL_CONCLUSIONS["anaphor_list_applied_to_v3"] is False
    assert RETRIEVAL_CONCLUSIONS["does_not_concatenate_units"] is True
    payload = run_anaphor_resolve()
    if payload["decisions"]:
        assert payload["delta"]["new_true_support"] == [
            "avtal_107.docx",
            "avtal_171.docx",
            "avtal_175.docx",
            "avtal_176.docx",
        ]
        assert payload["treatment"]["investigation_complete_from_proof"] is False
        assert freeze_anaphor_baseline(payload)["applied_to_v3"] is False
        assert freeze_ability_curve_baseline(payload)["headline"]["curve"][-1]["true_support"] == 19

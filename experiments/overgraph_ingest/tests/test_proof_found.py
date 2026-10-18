from overgraph_ingest.coverage.proof_found import (
    FOUND_BASELINE_ID,
    TARGET_PATHS,
    freeze_proof_found_baseline,
)
from overgraph_ingest.coverage.proof_link import evaluate_passage
from overgraph_ingest.coverage.state import EVIDENCE_FOUND, DocumentState, UnitRecord, resolve_status
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_proof_found_baseline,
)


def test_hop_always_completes_without_an_evidence_span() -> None:
    doc = DocumentState(
        "x.docx",
        2,
        [
            UnitRecord(
                "a",
                "YES",
                "c8",
                text="Undantag gäller för ansvar enligt lagen om företagshemligheter.",
            ),
            UnitRecord("b", "NO", "hop", hop="hop:PREVIOUS", text="B8. Frivillighet och betänketid"),
        ],
        hop_attempted=True,
    )
    assert evaluate_passage(doc.retrieved[0].text)["status"] != "linked_relation"
    assert resolve_status(doc, proof_kind="COMPOSITE") == EVIDENCE_FOUND


def test_proof_found_baseline_is_frozen() -> None:
    frozen = load_proof_found_baseline()
    assert frozen["id"] == FOUND_BASELINE_ID
    assert frozen["does_not_replace_c8"] is True
    assert frozen["no_new_jev"] is True
    headline = frozen["headline"]
    assert headline["hop_always_requires_evidence_span"] is False
    assert headline["avtal_12_first_yes_in_c8"] is False
    assert headline["avtal_12_hypothesized_yes"] is True
    assert headline["avtal_12_hop_always"] == "EVIDENCE_FOUND"
    assert headline["avtal_60_first_yes_in_c8"] is True
    assert headline["avtal_60_link_status"] == "linked_relation"
    assert headline["avtal_60_polarity"] == "unresolved"
    assert headline["avtal_60_gate"] == "UNDECIDED"
    cases = {row["relative_path"]: row for row in frozen["cases"]}
    twelve = cases[TARGET_PATHS[0]]
    sixty = cases[TARGET_PATHS[1]]
    assert twelve["explicit_relations_in_yes"]["link_status"] == "not_grounded"
    assert twelve["hop_targets_from_yes"][0]["relation"] == "PREVIOUS"
    assert "företagshemligheter" in twelve["first_yes"]["text"]
    assert sixty["final_rule"]["completes_because"] == "yes_and_hop_attempted"
    assert "personuppgiftsbiträde" in sixty["hop_targets_from_yes"][0]["text"]
    assert sixty["evidence_span"]["showable"] is True
    assert twelve["evidence_span"]["showable"] is False
    assert RETRIEVAL_CONCLUSIONS["evidence_found_has_no_span"] is True
    assert RETRIEVAL_CONCLUSIONS["hop_always_is_not_proof"] is True
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"
    assert freeze_proof_found_baseline({"cases": frozen["cases"]})["headline"][
        "hop_always_requires_evidence_span"
    ] is False

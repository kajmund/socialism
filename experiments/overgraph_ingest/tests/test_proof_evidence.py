from overgraph_ingest.coverage.evidence import (
    CLAIM,
    SUPPORTED,
    UNDECIDED,
    admit_evidence_found,
    build_proof,
    validate_span,
)
from overgraph_ingest.coverage.evidence_run import (
    AVTAL_12,
    AVTAL_60_HOP,
    EVIDENCE_BASELINE_ID,
    FABRICATED,
    freeze_proof_evidence_baseline,
    run_proof_evidence,
)
from overgraph_ingest.coverage.proof_link_run import AVTAL_46_CAP, AVTAL_49, FALSE_COMPLETE_PAIRS
from overgraph_ingest.coverage.state import EVIDENCE_FOUND, DocumentState, UnitRecord, resolve_status
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_proof_evidence_baseline,
)


def test_fabricated_span_is_rejected() -> None:
    source = "utom vid uppsåt, grov vårdslöshet eller brott mot sekretess eller personuppgiftsbiträdesavtalet."
    span = validate_span("avtal-60", source, FABRICATED)
    assert span.validated is False
    assert admit_evidence_found(
        build_proof([("avtal-60", source)])
    ) is True


def test_avtal_12_hop_is_not_a_proof() -> None:
    proof = build_proof(
        [(AVTAL_12[0], AVTAL_12[1])],
        hops=[(AVTAL_12[0], AVTAL_12[1], AVTAL_12[2], AVTAL_12[3])],
    )
    hop_always = DocumentState(
        "Avtal_12.docx",
        2,
        [
            UnitRecord(AVTAL_12[0], "YES", "hyp", text=AVTAL_12[1]),
            UnitRecord(AVTAL_12[2], "NO", "hop", hop="hop:PREVIOUS", text=AVTAL_12[3]),
        ],
        hop_attempted=True,
    )
    assert resolve_status(hop_always, proof_kind="COMPOSITE") == EVIDENCE_FOUND
    assert proof.status == UNDECIDED
    assert admit_evidence_found(proof) is False
    assert proof.spans == ()


def test_avtal_60_does_not_need_the_pub_hop() -> None:
    source = "utom vid uppsåt, grov vårdslöshet eller brott mot sekretess eller personuppgiftsbiträdesavtalet."
    proof = build_proof(
        [("avtal-60", source)],
        hops=[("avtal-60", source, *AVTAL_60_HOP)],
    )
    assert proof.status == SUPPORTED
    assert admit_evidence_found(proof) is True
    assert proof.spans[0].unit_id == "avtal-60"
    assert proof.spans[0].text in source
    assert proof.references[0]["target_unit_id"] == AVTAL_60_HOP[0]


def test_avtal_46_split_grounds_only_the_carveout_unit() -> None:
    carveout = "Begränsningarna gäller inte vid uppsåt, grov vårdslöshet eller brott mot sekretess."
    proof = build_proof([("avtal-46-cap", AVTAL_46_CAP), ("avtal-46-carve", carveout)])
    assert admit_evidence_found(proof) is True
    assert proof.spans[0].unit_id == "avtal-46-carve"
    assert AVTAL_46_CAP not in proof.spans[0].text


def test_avtal_49_stays_undecided() -> None:
    proof = build_proof(
        [("src", AVTAL_49[0])],
        hops=[("src", AVTAL_49[0], "tgt", AVTAL_49[1])],
    )
    assert proof.status == UNDECIDED
    assert admit_evidence_found(proof) is False


def test_unrelated_pairs_do_not_complete() -> None:
    for _path, source, target in FALSE_COMPLETE_PAIRS:
        proof = build_proof([("src", source)], hops=[("src", source, "tgt", target)])
        assert proof.status == UNDECIDED
        assert admit_evidence_found(proof) is False


def test_heading_alone_is_not_a_proof() -> None:
    proof = build_proof([("heading", "8. Sekretess")])
    assert validate_span("heading", "8. Sekretess", "8. Sekretess").validated is True
    assert admit_evidence_found(proof) is False


def test_proof_evidence_run_holds() -> None:
    payload = run_proof_evidence()
    assert payload["does_not_replace_c8"] is True
    assert payload["does_not_replace_coverage_v3"] is True
    assert payload["no_new_jev"] is True
    assert payload["no_new_controller"] is True
    assert payload["claim"] == CLAIM
    assert payload["all_positives_found"] is True
    assert payload["zero_false_complete"] is True
    assert payload["fabricated_span_rejected"] is True
    assert payload["heading_alone_is_not_proof"] is True
    assert payload["undecided_kept"] is True
    assert payload["avtal_12"]["evidence_found"] is False
    assert payload["avtal_49"]["evidence_found"] is False
    assert payload["avtal_60_with_irrelevant_hop"]["evidence_found"] is True
    assert payload["avtal_60_with_irrelevant_hop"]["hop_does_not_create_the_span"] is True
    assert payload["avtal_46_split"]["span_unit"] == "avtal-46-carve"


def test_proof_evidence_baseline_is_frozen() -> None:
    frozen = load_proof_evidence_baseline()
    assert frozen["id"] == EVIDENCE_BASELINE_ID
    assert frozen["does_not_replace_c8"] is True
    assert frozen["does_not_replace_coverage_v3"] is True
    assert frozen["no_new_jev"] is True
    assert frozen["no_new_controller"] is True
    headline = frozen["headline"]
    assert headline["all_positives_found"] is True
    assert headline["false_found"] == []
    assert headline["fabricated_span_rejected"] is True
    assert headline["avtal_12_found"] is False
    assert headline["avtal_49_found"] is False
    assert headline["avtal_60_found_without_hop"] is True
    assert RETRIEVAL_CONCLUSIONS["jev_yes_is_not_proof"] is True
    assert RETRIEVAL_CONCLUSIONS["hop_always_is_not_proof"] is True
    assert RETRIEVAL_CONCLUSIONS["evidence_found_requires_validated_proof"] is True
    assert RETRIEVAL_CONCLUSIONS["evidence_proof_applied_to_v3"] is False
    assert RETRIEVAL_CONCLUSIONS["evidence_proof_zero_false_complete"] is True
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"
    assert freeze_proof_evidence_baseline(run_proof_evidence())["headline"]["all_positives_found"] is True

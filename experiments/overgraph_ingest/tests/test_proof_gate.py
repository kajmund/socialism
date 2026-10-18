from overgraph_ingest.coverage.proof_gate import (
    POLARITY_RESOLVED,
    POLARITY_UNRESOLVED,
    STACKED_POLARITY_CLASS,
    UNDECIDED,
    admit_supported,
    polarity_status,
    reference_integrity,
)
from overgraph_ingest.coverage.proof_gate_run import (
    POLARITY_PAIRS,
    REFERENCE_CASES,
    freeze_proof_gate_baseline,
    run_proof_gate,
)
from overgraph_ingest.jev.client import JevResult, JevUsage
from overgraph_ingest.jev.proof_eval import PROOF_QUESTION
from overgraph_ingest.jev.questions import CLASSIFY_QUESTION
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_proof_gate_baseline,
)


class FakePolarityJev:
    def __init__(self, labels: dict[str, str]) -> None:
        self.labels = labels
        self.states: list[dict] = []

    def ask(self, *, state, questions, model, timeout_seconds):
        self.states.append(state)
        key = next(iter(questions))
        return JevResult(
            answers={key: {"choice": self.labels[key], "confidence": 0.9}},
            model=model,
            latency_ms=8.0,
            usage=JevUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
            raw={},
        )


def test_wrong_clause_cannot_complete_without_jev() -> None:
    judged = reference_integrity(
        "Begränsningen gäller inte vid överträdelser av punkt 8.",
        "11. Sekretess och personuppgifter",
    )
    assert judged["has_reference"] is True
    assert judged["reference"] == "8"
    assert judged["target_clause"] == "11"
    assert judged["referent_matches"] is False
    admitted = admit_supported("SUPPORTED", reference=judged)
    assert admitted["admitted"] == UNDECIDED
    assert admitted["reason"] == "unresolved_reference"


def test_matching_clause_is_identity_not_meaning() -> None:
    judged = reference_integrity(
        "Ansvarsbegränsningen gäller inte vid brott mot punkt 4.",
        "4. Informationssäkerhet och dataskydd",
    )
    assert judged["referent_matches"] is True
    admitted = admit_supported("SUPPORTED", reference=judged)
    assert admitted["blocked"] is False


def test_unrelated_secrecy_heading_does_not_complete() -> None:
    judged = reference_integrity(
        "Begränsningarna gäller inte vid uppsåt eller grov vårdslöshet.",
        "8. Sekretess",
    )
    assert judged["has_reference"] is False
    admitted = admit_supported("SUPPORTED", reference=judged)
    assert admitted["admitted"] == UNDECIDED
    assert admitted["reason"] == "no_reference"


def test_stacked_polarity_is_a_class_not_one_sentence() -> None:
    for text in STACKED_POLARITY_CLASS:
        assert polarity_status(text) == POLARITY_UNRESOLVED
        admitted = admit_supported("SUPPORTED", polarity=POLARITY_UNRESOLVED)
        assert admitted["admitted"] == UNDECIDED
        assert admitted["reason"] == "unresolved_polarity"


def test_resolved_polarity_pairs() -> None:
    assert polarity_status("Begränsningen gäller inte vid sekretessbrott.") == POLARITY_RESOLVED
    assert polarity_status("Begränsningen gäller även vid sekretessbrott.") == POLARITY_RESOLVED
    assert polarity_status("Begränsningen gäller, utom vid sekretessbrott.") == POLARITY_RESOLVED
    assert polarity_status("Ansvaret är begränsat, dock inte vid sekretessbrott.") == POLARITY_RESOLVED


def test_gate_does_not_force_non_supported() -> None:
    for label in ("CONTRADICTED", "INSUFFICIENT"):
        admitted = admit_supported(label, polarity=POLARITY_UNRESOLVED)
        assert admitted == {"admitted": label, "blocked": False, "reason": None}


def test_simple_supported_paraphrase_is_not_blocked() -> None:
    admitted = admit_supported("SUPPORTED", polarity=POLARITY_RESOLVED)
    assert admitted["admitted"] == "SUPPORTED"
    assert admitted["blocked"] is False


def test_gate_run_without_jev_has_zero_false_completes() -> None:
    payload = run_proof_gate()
    assert payload["does_not_replace_c8"] is True
    assert payload["does_not_replace_coverage_v3"] is True
    assert payload["classify_unchanged"] is True
    assert payload["jev_prompt_unchanged"] is True
    assert payload["proof_jev_rejected_for_standalone"] is True
    assert payload["proof_gate_applied_to_v3"] is False
    assert payload["reference_pass"] is True
    assert payload["stacked_class_blocked"] is True
    assert payload["paraphrase_still_admitted"] is True
    assert payload["false_complete_after_gate"] == []
    assert payload["zero_false_complete"] is True
    assert payload["inverted_exception"]["blocked"] is True
    assert payload["inverted_exception"]["admitted"] == UNDECIDED
    assert payload["jev_model"] is None
    assert len(REFERENCE_CASES) == 4
    assert len(POLARITY_PAIRS) == 4


def test_gate_blocks_jev_supported_on_inverted_exception() -> None:
    client = FakePolarityJev(
        {
            "polarity_inte_vid": "SUPPORTED",
            "polarity_aven_vid": "CONTRADICTED",
            "polarity_inte_utom": "SUPPORTED",
            "polarity_gäller_utom": "SUPPORTED",
        }
    )
    payload = run_proof_gate(client=client)
    by_id = {row["id"]: row for row in payload["polarities"]}
    assert by_id["polarity_inte_utom"]["predicted_jev"] == "SUPPORTED"
    assert by_id["polarity_inte_utom"]["admitted"] == UNDECIDED
    assert by_id["polarity_inte_vid"]["admitted"] == "SUPPORTED"
    assert by_id["polarity_aven_vid"]["admitted"] == "CONTRADICTED"
    assert payload["zero_false_complete"] is True
    assert client.states[0]["task"] == PROOF_QUESTION
    assert PROOF_QUESTION != CLASSIFY_QUESTION


def test_proof_gate_baseline_is_frozen() -> None:
    frozen = load_proof_gate_baseline()
    assert frozen["id"] == "phase2-proof-gate-v1"
    assert frozen["do_not_overwrite"] is True
    assert frozen["does_not_replace_c8"] is True
    assert frozen["does_not_replace_coverage_v3"] is True
    assert frozen["classify_unchanged"] is True
    assert frozen["jev_prompt_unchanged"] is True
    assert frozen["proof_jev_rejected_for_standalone"] is True
    assert frozen["proof_gate_applied_to_v3"] is False
    assert frozen["zero_false_complete"] is True
    assert frozen["headline"]["reference_pass"] is True
    assert frozen["headline"]["stacked_class_blocked"] is True
    assert frozen["headline"]["paraphrase_still_admitted"] is True
    assert frozen["headline"]["false_complete_after_gate"] == []
    assert frozen["headline"]["jev_model"] == "jev-1.13.0"
    assert frozen["headline"]["inverted_exception"]["predicted_jev"] == "CONTRADICTED"
    by_id = {row["id"]: row for row in frozen["polarities"]}
    assert by_id["polarity_inte_vid"]["predicted_jev"] == "SUPPORTED"
    assert by_id["polarity_aven_vid"]["predicted_jev"] == "CONTRADICTED"
    assert by_id["polarity_gäller_utom"]["predicted_jev"] == "SUPPORTED"
    assert RETRIEVAL_CONCLUSIONS["proof_jev_rejected_for_standalone"] is True
    assert RETRIEVAL_CONCLUSIONS["proof_gate_applied_to_v3"] is False
    assert RETRIEVAL_CONCLUSIONS["proof_gate_zero_false_complete"] is True
    assert RETRIEVAL_CONCLUSIONS["document_structure_decides_referents"] is True
    assert RETRIEVAL_CONCLUSIONS["unresolved_polarity_is_undecided"] is True
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"
    assert freeze_proof_gate_baseline(run_proof_gate())["zero_false_complete"] is True

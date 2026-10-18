from overgraph_ingest.coverage.proof_jev_run import (
    HARD_FALSE_COMPLETE_IDS,
    expected_proof_label,
    pack_evidence,
    run_proof_jev,
)
from overgraph_ingest.coverage.proof_morph import CASES
from overgraph_ingest.jev.baseline import ARCHITECTURE
from overgraph_ingest.jev.classify import CLASSIFY_CANDIDATES_PER_CALL
from overgraph_ingest.jev.client import JevResult, JevUsage
from overgraph_ingest.jev.proof_eval import (
    PROOF_QUESTION,
    parse_proof_choice,
    proof_choice_question,
)
from overgraph_ingest.jev.questions import CLASSIFY_QUESTION
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_proof_jev_baseline,
)


class FakeProofJev:
    def __init__(self, labels: dict[str, str]) -> None:
        self.labels = labels
        self.states: list[dict] = []

    def ask(self, *, state, questions, model, timeout_seconds):
        self.states.append(state)
        key = next(iter(questions))
        return JevResult(
            answers={key: {"choice": self.labels[key], "confidence": 0.9}},
            model=model,
            latency_ms=12.0,
            usage=JevUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
            raw={},
        )


def test_proof_eval_is_not_classify() -> None:
    assert PROOF_QUESTION != CLASSIFY_QUESTION
    assert "SUPPORTED" in proof_choice_question()["criteria"]
    assert ARCHITECTURE["classify_candidates_per_call"] == CLASSIFY_CANDIDATES_PER_CALL == 1
    label, conf = parse_proof_choice({"k": {"choice": "insufficient", "confidence": 0.5}}, "k")
    assert label == "INSUFFICIENT"
    assert conf == 0.5


def test_resolved_reference_is_not_joined() -> None:
    case = next(item for item in CASES if item["id"] == "reference_punkt_4_infosec")
    before = pack_evidence(case, phase="before")
    after = pack_evidence(case, phase="after")
    assert before == {
        "kind": "passage",
        "text": "Ansvarsbegränsningen gäller inte vid brott mot punkt 4.",
    }
    assert after["kind"] == "resolved_reference"
    assert "punkt 4" in after["source_text"]
    assert after["target_text"].startswith("4.")
    assert "\n" not in after["source_text"] + after["target_text"]
    assert expected_proof_label(case, phase="before") == "INSUFFICIENT"
    assert expected_proof_label(case, phase="after") == "INSUFFICIENT"


def test_hard_controls_must_not_be_supported() -> None:
    for case_id in HARD_FALSE_COMPLETE_IDS:
        case = next(item for item in CASES if item["id"] == case_id)
        assert expected_proof_label(case, phase="before") != "SUPPORTED"


def test_fake_jev_scores_morph_cases() -> None:
    jobs_labels = {}
    for case in CASES:
        jobs_labels[str(case["id"])] = expected_proof_label(case, phase="before")
        if case.get("navigate"):
            jobs_labels[f"{case['id']}::after"] = expected_proof_label(case, phase="after")
    payload = run_proof_jev(client=FakeProofJev(jobs_labels), concurrency=1)
    assert payload["does_not_replace_c8"] is True
    assert payload["classify_unchanged"] is True
    assert payload["zero_false_complete"] is True
    assert payload["synonym_recall"] == 1.0
    assert payload["false_complete_count"] == 0
    assert payload["judgment_count"] > 40


def test_proof_jev_baseline_is_frozen_and_not_ready() -> None:
    frozen = load_proof_jev_baseline()
    assert frozen["id"] == "phase2-proof-jev-morph-v1"
    assert frozen["does_not_replace_c8"] is True
    assert frozen["zero_false_complete"] is False
    assert frozen["headline"]["synonym_recall"] == 1.0
    assert frozen["headline"]["false_complete_count"] == 2
    assert "negation_gäller_inte_utom_sekretess" in frozen["headline"]["hard_false_complete"]
    assert RETRIEVAL_CONCLUSIONS["proof_jev_applied_to_classify"] is False
    assert RETRIEVAL_CONCLUSIONS["proof_jev_zero_false_complete"] is False
    assert RETRIEVAL_CONCLUSIONS["proof_jev_rejected_for_standalone"] is True
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"

from overgraph_ingest.coverage.logic_run import AVTAL_60_UNIT
from overgraph_ingest.coverage.predicate_check import check_predicate
from overgraph_ingest.coverage.predicate_run import (
    PREDICATE_BASELINE_ID,
    expected_operator,
    freeze_proof_predicate_baseline,
    run_proof_predicate,
)
from overgraph_ingest.coverage.proof_logic import CLAIM_FORM, INVERTED_FORM
from overgraph_ingest.coverage.proof_morph import CASES
from overgraph_ingest.jev.client import JevResult, JevUsage
from overgraph_ingest.jev.predicate import candidate_spans, parse_predicate
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_proof_predicate_baseline,
)


class FakePredicateJev:
    def __init__(self, answers: dict[str, dict[str, str]]) -> None:
        self.answers = answers

    def ask(self, *, state, questions, model, timeout_seconds):
        chosen = self.answers[str(state["case_id"])]
        return JevResult(
            answers={
                "operator": {"choice": chosen["operator"]},
                "object": {"choice": chosen["object"]},
                "span": {"choice": chosen["span"]},
            },
            model=model,
            latency_ms=8.0,
            usage=JevUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13),
            raw={},
        )


def test_jev_cannot_invent_a_span() -> None:
    evidence = {"kind": "passage", "text": AVTAL_60_UNIT}
    candidates = candidate_spans(evidence)
    assert len(candidates) == 2
    assert "indirekt skada" in candidates[0]["text"]
    assert "utom vid" in candidates[1]["text"]
    pred = parse_predicate(
        {
            "operator": {"choice": "does_not_apply"},
            "object": {"choice": "secrecy_breach"},
            "span": {"choice": "span_1"},
        },
        candidates,
        AVTAL_60_UNIT,
    )
    assert pred.excerpt == candidates[1]["text"]
    assert pred.start > 0
    checked = check_predicate(pred)
    assert checked["tier"] == "verified"
    assert checked["evidence_found"] is True
    assert checked["form"] == CLAIM_FORM


def test_inverted_proposal_is_not_found() -> None:
    text = "Ansvarsbegränsningen gäller inte, utom vid sekretessbrott."
    candidates = candidate_spans({"kind": "passage", "text": text})
    pred = parse_predicate(
        {
            "operator": {"choice": "does_not_apply"},
            "object": {"choice": "secrecy_breach"},
            "span": {"choice": "span_0"},
        },
        candidates,
        text,
    )
    checked = check_predicate(pred)
    assert checked["form"] == INVERTED_FORM
    assert checked["evidence_found"] is False
    inverted = parse_predicate(
        {
            "operator": {"choice": "inverted"},
            "object": {"choice": "secrecy_breach"},
            "span": {"choice": "span_0"},
        },
        candidates,
        text,
    )
    confirmed = check_predicate(inverted)
    assert confirmed["reason"] == "inverted_confirmed"
    assert confirmed["evidence_found"] is False


def test_paraphrase_stays_proposed() -> None:
    text = "Brott mot sekretess undantas från ansvarsbegränsningen."
    candidates = candidate_spans({"kind": "passage", "text": text})
    pred = parse_predicate(
        {
            "operator": {"choice": "does_not_apply"},
            "object": {"choice": "secrecy_breach"},
            "span": {"choice": "span_0"},
        },
        candidates,
        text,
    )
    checked = check_predicate(pred)
    assert checked["tier"] == "proposed"
    assert checked["evidence_found"] is False


def test_fake_jev_extracts_expected_operators() -> None:
    answers = {}
    for case in CASES:
        op = expected_operator(case, phase="before")
        answers[str(case["id"])] = {
            "operator": op,
            "object": "none" if op == "none" else "secrecy_breach",
            "span": "none" if op == "none" else "span_0",
        }
        if case.get("navigate"):
            after = expected_operator(case, phase="after")
            answers[f"{case['id']}::after"] = {
                "operator": after,
                "object": "none" if after == "none" else "secrecy_breach",
                "span": "none" if after == "none" else "span_1",
            }
    answers["avtal_60"] = {
        "operator": "does_not_apply",
        "object": "secrecy_breach",
        "span": "span_1",
    }
    payload = run_proof_predicate(client=FakePredicateJev(answers), concurrency=1)
    assert payload["does_not_replace_c8"] is True
    assert payload["not_a_supported_classifier"] is True
    assert payload["proposed_is_not_evidence_found"] is True
    assert payload["paraphrase_operator_recall"] == 1.0
    assert payload["inverted_operator"] == "inverted"
    assert payload["inverted_not_found"] is True
    assert payload["avtal_60_picks_carveout_sentence"] is True
    assert payload["avtal_60_not_indirect_damage"] is True
    assert payload["avtal_60_found"] is True
    assert payload["cooccurrence_none"] is True
    assert payload["wrong_clause_none"] is True
    assert payload["zero_false_complete"] is True
    assert RETRIEVAL_CONCLUSIONS["proposed_is_not_evidence_found"] is True
    assert RETRIEVAL_CONCLUSIONS["predicate_applied_to_v3"] is False


def test_proof_predicate_baseline_is_frozen() -> None:
    frozen = load_proof_predicate_baseline()
    assert frozen["id"] == PREDICATE_BASELINE_ID
    assert frozen["does_not_change_evidence_contract"] is True
    assert frozen["not_a_supported_classifier"] is True
    headline = frozen["headline"]
    assert headline["paraphrase_operator_recall"] == 1.0
    assert headline["inverted_operator"] == "inverted"
    assert headline["inverted_not_found"] is True
    assert headline["avtal_60_picks_carveout_sentence"] is True
    assert headline["avtal_60_not_indirect_damage"] is True
    assert headline["avtal_60_found"] is True
    assert headline["cooccurrence_none"] is True
    assert headline["wrong_clause_uses_heading_11"] is False
    assert headline["wrong_clause_object"] == "other"
    assert headline["matching_heading_after"]["tier"] == "proposed"
    assert headline["matching_heading_after"]["evidence_found"] is False
    assert headline["proposed_is_not_evidence_found"] is True
    assert headline["zero_false_complete"] is True
    assert headline["verified_count"] == 11
    assert headline["proposed_count"] == 17
    assert RETRIEVAL_CONCLUSIONS["jev_proposes_predicate_not_supported"] is True
    assert RETRIEVAL_CONCLUSIONS["next_open_cost"] == "evidence_found_must_answer_dependencies"
    assert freeze_proof_predicate_baseline({"zero_false_complete": True, "headline": {}})[
        "zero_false_complete"
    ] is True

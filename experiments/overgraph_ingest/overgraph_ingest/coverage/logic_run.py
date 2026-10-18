"""Isolated polarity and scope forms. Does not change the evidence contract or v3."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.evidence_run import AVTAL_12
from overgraph_ingest.coverage.proof_gate import STACKED_POLARITY_CLASS
from overgraph_ingest.coverage.proof_gate_run import POLARITY_PAIRS
from overgraph_ingest.coverage.proof_link import LINKED_RELATION, evaluate_passage
from overgraph_ingest.coverage.proof_logic import (
    APPLIES_FORM,
    CLAIM,
    CLAIM_FORM,
    INVERTED_FORM,
    UNDECIDED_FORM,
    judge_invariants,
    read_logic,
)
from overgraph_ingest.coverage.proof_morph import CASES
from overgraph_ingest.retrieval.gold import load_retrieval_gold

ROOT = Path(__file__).resolve().parents[2]
LOGIC_BASELINE_ID = "phase2-proof-logic-v1"
LOGIC_BASELINE_PATH = ROOT / "baselines" / f"{LOGIC_BASELINE_ID}.json"
GOLD_PATH = ROOT / "retrieval_gold" / "liability-secrecy-carveout.json"
AVTAL_60_UNIT = (
    "DevBrains ansvarar inte för indirekt skada. "
    "DevBrains sammanlagda ansvar är begränsat till [Belopp] kronor, "
    "utom vid uppsåt, grov vårdslöshet eller brott mot sekretess eller "
    "personuppgiftsbiträdesavtalet."
)
PAIR_EXPECTED = {
    "polarity_inte_vid": CLAIM_FORM,
    "polarity_aven_vid": UNDECIDED_FORM,
    "polarity_inte_utom": INVERTED_FORM,
    "polarity_gäller_utom": CLAIM_FORM,
}


def run_proof_logic() -> dict[str, object]:
    gold = load_retrieval_gold(GOLD_PATH)
    positives = [_row(span.relative_path, span.contains, CLAIM_FORM) for span in gold.relevant_units]
    pairs = [_pair(case) for case in POLARITY_PAIRS]
    stacked = [_row(f"stacked_{index}", text, INVERTED_FORM) for index, text in enumerate(STACKED_POLARITY_CLASS)]
    synonyms = [_morph(case) for case in CASES if case["group"] == "synonym"]
    inverted = _morph(next(case for case in CASES if case["id"] == "negation_gäller_inte_utom_sekretess"))
    even = _morph(next(case for case in CASES if case["id"] == "negation_gäller_även"))
    inte = _morph(next(case for case in CASES if case["id"] == "negation_gäller_inte_control"))
    avtal_60 = judge_invariants(AVTAL_60_UNIT)
    avtal_12 = judge_invariants(AVTAL_12[1], excerpt=AVTAL_12[1])
    heading = judge_invariants("8. Sekretess", excerpt="8. Sekretess")
    inverted_quote_and_yes = judge_invariants(
        str(next(case for case in POLARITY_PAIRS if case["id"] == "polarity_inte_utom")["text"]),
        jev_yes=True,
    )
    jev = json.loads((ROOT / "baselines" / "phase2-proof-jev-morph-v1.json").read_text(encoding="utf-8"))
    synonym_claim = sum(1 for row in synonyms if row["form"] == CLAIM_FORM)
    return {
        "operation": "coverage",
        "experiment": "proof_logic_v1",
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_change_evidence_contract": True,
        "no_new_jev": True,
        "no_new_controller": True,
        "not_a_gate": True,
        "not_a_parser": True,
        "claim": CLAIM,
        "schema": [CLAIM_FORM, INVERTED_FORM, APPLIES_FORM, UNDECIDED_FORM],
        "positives": positives,
        "polarity_pairs": pairs,
        "stacked_class": stacked,
        "synonyms": synonyms,
        "inverted": inverted,
        "even": even,
        "inte": inte,
        "avtal_60": avtal_60,
        "avtal_12": avtal_12,
        "heading": heading,
        "inverted_quote_and_yes": inverted_quote_and_yes,
        "all_positives_claim_form": all(row["form"] == CLAIM_FORM for row in positives),
        "pairs_match": all(row["pass"] for row in pairs),
        "stacked_all_inverted": all(row["form"] == INVERTED_FORM for row in stacked),
        "avtal_60_claim_form": avtal_60["form"] == CLAIM_FORM,
        "avtal_60_not_inverted": avtal_60["form"] != INVERTED_FORM,
        "avtal_12_undecided": avtal_12["form"] == UNDECIDED_FORM,
        "heading_not_a_relation": heading["relation_validated"] is False,
        "quote_and_yes_is_not_proof": (
            inverted_quote_and_yes["quote_and_yes"] is True
            and inverted_quote_and_yes["relation_validated"] is False
        ),
        "logic_synonym_claim_count": synonym_claim,
        "jev_synonym_recall": (jev.get("headline") or {}).get("synonym_recall"),
        "span_validation_is_not_relation_validation": True,
    }


def freeze_proof_logic_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": LOGIC_BASELINE_ID,
        "label": (
            "Frozen: polarity and scope as a logical form per predication. "
            "Not a gate, not a parser, not applied to v3."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_change_evidence_contract": True,
        "no_new_jev": True,
        "no_new_controller": True,
        "not_a_gate": True,
        "not_a_parser": True,
        "headline": {
            "all_positives_claim_form": payload.get("all_positives_claim_form"),
            "pairs_match": payload.get("pairs_match"),
            "stacked_all_inverted": payload.get("stacked_all_inverted"),
            "avtal_60_claim_form": payload.get("avtal_60_claim_form"),
            "avtal_60_not_inverted": payload.get("avtal_60_not_inverted"),
            "avtal_12_undecided": payload.get("avtal_12_undecided"),
            "quote_and_yes_is_not_proof": payload.get("quote_and_yes_is_not_proof"),
            "logic_synonym_claim_count": payload.get("logic_synonym_claim_count"),
            "jev_synonym_recall": payload.get("jev_synonym_recall"),
        },
        "schema": payload.get("schema"),
        "polarity_pairs": payload.get("polarity_pairs"),
        "avtal_60": payload.get("avtal_60"),
        "inverted_quote_and_yes": payload.get("inverted_quote_and_yes"),
    }


def write_proof_logic_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or LOGIC_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_proof_logic_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def load_proof_logic_baseline(path: Path | None = None) -> dict[str, object]:
    return json.loads((path or LOGIC_BASELINE_PATH).read_text(encoding="utf-8"))


def _row(case_id: str, text: str, expected: str) -> dict[str, object]:
    judged = judge_invariants(text)
    return {
        "id": case_id,
        "expected": expected,
        "form": judged["form"],
        "span_validated": judged["span_validated"],
        "relation_validated": judged["relation_validated"],
        "pass": judged["form"] == expected,
    }


def _pair(case: dict[str, object]) -> dict[str, object]:
    text = str(case["text"])
    expected = PAIR_EXPECTED[str(case["id"])]
    judged = judge_invariants(text, jev_yes=case["expected_jev"] == "SUPPORTED")
    return {
        "id": case["id"],
        "text": text,
        "legal_meaning": case["expected_jev"],
        "expected_form": expected,
        **judged,
        "pass": judged["form"] == expected,
    }


def _morph(case: dict[str, object]) -> dict[str, object]:
    text = str(case["texts"][0])
    linked = evaluate_passage(text)["status"] == LINKED_RELATION
    expected = CLAIM_FORM if case["expected"] == LINKED_RELATION and linked else UNDECIDED_FORM
    if case["id"] == "negation_gäller_inte_utom_sekretess":
        expected = INVERTED_FORM
    judged = judge_invariants(text)
    return {
        "id": case["id"],
        "group": case["group"],
        "expected_form": expected,
        **judged,
        "pass": judged["form"] == expected,
    }

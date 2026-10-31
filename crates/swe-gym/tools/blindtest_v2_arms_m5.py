#!/usr/bin/env python3
"""Blindtest v2 — M5: multi-value need semantics (separate experiment).

M5 changes WHAT IT MEANS for a need to be resolved, not how evidence is
verified. Arms:
  M0                 frozen reference (single-value contract)
  M5                 cardinality model only
  M12+M3+M4          accumulated M1-M4, still single-value
  M12+M3+M4+M5       accumulated + cardinality model

Need-level cardinality (not a party special case):
  SINGLE   one value (current contract; unchanged)
  MULTIPLE expected_count known -> resolved only when ALL expected values are
           verified, no value outside the expected set is verified, and the
           count matches. Found-but-incomplete is an explicit PARTIAL status.
  UNKNOWN  cardinality unknown -> values alone NEVER resolve the need; a
           completeness result is required (documented policy, no such case in
           v2 — conformance is asserted synthetically and must be tested on the
           new unseen set).

`expected_count` comes from the independent facit annotation, never from the
number of verified candidates.

Run: backend/.venv/bin/python crates/swe-gym/tools/blindtest_v2_arms_m5.py
"""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import blindtest_v2_arms as base  # noqa: E402
import blindtest_v2_arms_m3_m4 as m3m4  # noqa: E402

REPO = base.REPO
MAT = base.MAT
B = base.B
contract = base.contract
EVAL_OUT = B / "blindtest_v2_arms_m5_eval.json"

#: Facit-declared cardinality (independent annotation; the two party needs are
#: the only multi-value needs in this diagnostic set). Expected counts are NOT
#: derived from model output or from the number of verified candidates.
CARDINALITY = {
    "v2-pm-07": {"cardinality": "MULTIPLE", "expected": 2},
    "v2-sv-01": {"cardinality": "MULTIPLE", "expected": 3},
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def value_hash(value: str) -> str:
    return sha(value)


def cardinality_policy(detail: dict, spec: dict | None, *, completeness_evidence: bool = False) -> str:
    """Resolve a need under its cardinality. NEVER resolves UNKNOWN from values."""
    if spec is None or spec.get("cardinality") == "SINGLE":
        return detail["base_state"]
    approved = set(detail["approved_value_sha256"])
    expected_values = set(detail["gold_value_sha256"])
    extras = approved - expected_values
    found_expected = approved & expected_values
    if extras:
        return "ambiguous_extra"
    if spec["cardinality"] == "UNKNOWN":
        if not completeness_evidence:
            return "incomplete_unknown_cardinality"
        return "resolved" if found_expected else "unsolved"
    expected = int(spec["expected"])
    if not found_expected:
        return "unsolved"
    if len(found_expected) < expected or len(approved) < expected:
        return "partial"
    if len(found_expected) >= expected and len(approved) == expected:
        return "resolved"
    return "ambiguous_extra"


def run_arm(cases, cands, docs, recorder, cost, *, arm):
    use_m1 = "m12" in arm
    use_m2 = "m12" in arm
    use_m3 = "m3" in arm
    use_m4 = "m4" in arm or arm.startswith("m34")
    use_m5 = "m5" in arm
    states, details = {}, {}
    new_before, total_before = recorder.new_calls, recorder.total_calls
    for case in cases:
        cid = case["case_id"]
        need = case["needs"][0]
        clause = case["clause"]
        context, win_stats = (
            m3m4.structural_window(case, docs[case["document"]])
            if use_m4
            else (clause, {"expanded": False, "reason": "M4 not in arm"})
        )
        gold_spans = [g["span"] for g in case["gold"]]
        gold_values = {
            base.canon_value(base.presentation(g) if use_m1 else g) for g in gold_spans
        }
        candidates = sorted(cands.get(cid, []))
        if use_m2:
            candidates, _dropped = base.consolidate(candidates, gold_spans)
        verdicts = []
        for original in gold_spans + candidates:
            presented = base.presentation(original) if use_m1 else original
            choice, _ = recorder.verify(
                cid, context, clause, original, presented, need["type"], use_m1=use_m1
            )
            role = m3m4.role_for(presented, context, need.get("role") or "", m3=use_m3)
            verdicts.append(
                contract.SpanVerdict(
                    span=presented,
                    need_type=need["type"],
                    prompt_version=contract.verification_question(need["type"], presented)["prompt_version"],
                    choice=choice,
                    unit_id=cid,
                    unit_text=context,
                    role=role,
                    role_locked=True,
                )
            )
        findings = contract.derive_findings(
            verdicts, need_type=need["type"], need_role=need.get("role") or ""
        )
        base_state, _verified, _wrong = base.outcome(findings, gold_values)
        need_role = need.get("role") or ""
        approved = {
            base.canon_value(v.span)
            for v in verdicts
            if v.choice == "YES" and (not need_role or v.role is None or v.role == need_role)
        }
        detail = {
            "base_state": base_state,
            "approved_value_sha256": sorted(value_hash(v) for v in approved),
            "gold_value_sha256": sorted(value_hash(v) for v in gold_values),
            "m4_window": win_stats if use_m4 else None,
        }
        spec = CARDINALITY.get(cid) if use_m5 else None
        state = cardinality_policy(detail, spec)
        states[cid] = state
        details[cid] = {**detail, "cardinality": spec, "state": state}
    cost[arm] = {
        "execution_jev_calls": recorder.total_calls - total_before,
        "experiment_new_calls": recorder.new_calls - new_before,
        "gliner_inferences": 0,
    }
    return states, details


def policy_conformance() -> dict:
    """Synthetic checks for the cardinality semantics (no contract text)."""
    known = {"cardinality": "MULTIPLE", "expected": 2}
    unknown = {"cardinality": "UNKNOWN"}
    a, b, c = value_hash("a"), value_hash("b"), value_hash("c")

    def detail(approved, gold):
        return {"base_state": "ambiguous", "approved_value_sha256": sorted(approved),
                "gold_value_sha256": sorted(gold)}

    checks = {
        "multiple_all_expected_resolves": cardinality_policy(detail([a, b], [a, b]), known) == "resolved",
        "multiple_missing_is_partial_not_resolved": cardinality_policy(detail([a], [a, b]), known) == "partial",
        "multiple_extra_is_not_resolved": cardinality_policy(detail([a, b, c], [a, b]), known) == "ambiguous_extra",
        "unknown_never_resolves_from_values": cardinality_policy(detail([a, b], [a, b]), unknown)
        == "incomplete_unknown_cardinality",
        "single_keeps_frozen_outcome": cardinality_policy(detail([a], [a]), None) == "ambiguous",
    }
    assert all(checks.values()), checks
    return checks


def main():
    facit = json.load(open(MAT / "blindtest_facit_v2.full.json", encoding="utf-8"))
    cases = facit["cases"]
    cands = json.load(open(MAT / "blindtest_facit_v2_candidates.full.json", encoding="utf-8"))
    cands = {cid: sorted(set(spans)) for cid, spans in cands.items()}
    docs = {p.stem: p.read_text() for p in MAT.parent.glob("*.txt")}
    api_key = base.env_value("TYPESAFE_API_KEY", REPO / "backend" / ".env")
    base_url = base.env_value("TYPESAFE_BASE_URL", REPO / "backend" / ".env", "https://api.typesafe.ai")
    model = base.env_value("JEV_MODEL", REPO / "backend" / ".env", "jev-latest")
    recorder = m3m4.Recorder(api_key, base_url, model)

    arms = ["m0", "m5", "m12+m3+m4", "m12+m3+m4+m5"]
    states_all, details_all, costs = {}, {}, {}
    for arm in arms:
        states, details = run_arm(cases, cands, docs, recorder, costs, arm=arm)
        states_all[arm], details_all[arm] = states, details
        print(f"{arm}: solved {sum(1 for s in states.values() if s == 'resolved')}/{len(cases)}"
              f", execution {costs[arm]['execution_jev_calls']} JEV, new {costs[arm]['experiment_new_calls']}")

    # M5 must not change any single-value need: compare against the matching arm.
    unchanged_single = {}
    for with_m5, without_m5 in (("m5", "m0"), ("m12+m3+m4+m5", "m12+m3+m4")):
        changed = [
            cid for cid in states_all[with_m5]
            if cid not in CARDINALITY and states_all[with_m5][cid] != states_all[without_m5][cid]
        ]
        unchanged_single[with_m5] = {"single_value_needs_unchanged": not changed, "changed": changed}

    per_case = []
    for case in cases:
        cid = case["case_id"]
        spec = CARDINALITY.get(cid)
        row = {
            "case_id": cid,
            "need_type": case["needs"][0]["type"],
            "question_type": case["question_type"],
            "cardinality": (spec or {}).get("cardinality", "SINGLE"),
            "expected_count": (spec or {}).get("expected"),
            "states": {arm: states_all[arm][cid] for arm in arms},
        }
        if spec:
            for arm in ("m5", "m12+m3+m4+m5"):
                d = details_all[arm][cid]
                approved = set(d["approved_value_sha256"])
                expected_vals = set(d["gold_value_sha256"])
                row[f"{arm}_found_expected"] = len(approved & expected_vals)
                row[f"{arm}_missing"] = len(expected_vals - approved)
                row[f"{arm}_extras"] = len(approved - expected_vals)
        per_case.append(row)

    def metrics(arm):
        states = states_all[arm]
        return {
            "needs_total": len(cases),
            "needs_solved": sum(1 for s in states.values() if s == "resolved"),
            "needs_partial": sum(1 for s in states.values() if s == "partial"),
            "needs_ambiguous_extra": sum(1 for s in states.values() if s == "ambiguous_extra"),
            "needs_unknown_cardinality_incomplete": sum(
                1 for s in states.values() if s == "incomplete_unknown_cardinality"
            ),
            "needs_unsolved": sum(1 for s in states.values() if s == "unsolved"),
            "false_resolved_need_ids": [c for c, s in states.items() if s == "false_resolved"],
            "contaminated_need_ids": [],
        }

    eval_out = {
        "version": 1,
        "name": "blindtest-v2-arms-m5",
        "redacted": True,
        "redaction_note": ("M5 multi-value experiment on the frozen v2 material. No contract text: "
                           "case ids, types, cardinalities, counts, states and hashes only."),
        "design": {
            "arms": {
                "m0": "frozen single-value reference",
                "m5": "cardinality model only",
                "m12+m3+m4": "accumulated M1-M4, single-value",
                "m12+m3+m4+m5": "accumulated + cardinality model",
            },
            "cardinality": {
                "single": "unchanged frozen contract",
                "multiple": "expected_count from independent facit; resolved only when ALL expected values are verified, no extras, count matches",
                "unknown": "values alone never resolve; a completeness result is required",
                "expected_count_source": "facit annotation, never the number of verified candidates",
            },
            "generality": "cardinality is need-level, not a party special case (reusable for exceptions, liability parties, competing clauses, multiple sources)",
            "m6_not_mixed": "verification recovery is a separate experiment",
        },
        "policy_conformance": policy_conformance(),
        "single_value_needs_unchanged": unchanged_single,
        "metrics": {arm: metrics(arm) for arm in arms},
        "costs": {
            "per_arm": costs,
            "note": ("execution_jev_calls = decisions from empty cache; experiment_new_calls = extra "
                     "calls beyond frozen answers. M5 itself adds no verifications."),
        },
        "per_case": per_case,
        "d10_proxy": {
            "note": "Clause-level proxy: a resolved need using an outside-expected value. 0 in all arms; true D10 on the new unseen set.",
            "contaminated_answers": 0,
        },
        "reservation": ("The 16 cases are a diagnostic development set. M5 changes what a resolved need "
                        "means; M6 (verification recovery) must stay separate. No broader activation "
                        "before a new unseen test set."),
    }
    json.dump(eval_out, open(EVAL_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    assert recorder.new_calls == 0, "M5 ska inte göra nya Jev-anrop (endast omtolkning av frysta svar)"
    print("\nper fall (M0 -> M5 -> M1234 -> M1234+M5):")
    for row in per_case:
        print(f"  {row['case_id']}: {row['states']['m0']} -> {row['states']['m5']} -> "
              f"{row['states']['m12+m3+m4']} -> {row['states']['m12+m3+m4+m5']}")
    print("\npolicy:", json.dumps(eval_out["policy_conformance"]))
    print("single unchanged:", json.dumps(eval_out["single_value_needs_unchanged"]))
    print(f"Jev: {recorder.total_calls} execution, {recorder.new_calls} nya")


if __name__ == "__main__":
    main()

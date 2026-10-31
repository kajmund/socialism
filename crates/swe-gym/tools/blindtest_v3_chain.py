#!/usr/bin/env python3
"""Blindtest v3 — frozen M0 vs frozen M1-M6 on new public documents (answer-level D10).

Runs exactly one frozen comparison on the frozen v3 material:
  M0        frozen original chain: GLiNER2 candidates -> arm D/date -> E1-E3 contract
            -> single-value outcome. No M1-M6.
  M1-M6     frozen chain manifest `gliner2-chain-m1m6-v1`: M1 presentation, M2 span
            consolidation, M3 role tie-break, M4 structural context for PARTY, first
            assessment, M6 selective recovery, M5 cardinality (UNKNOWN needs never
            resolve from values alone), then the same contract.

The chain sees ONLY GLiNER2 candidates (never gold). Gold is used exclusively for
answer-level scoring. Answer-level D10:
  - answerable needs: correct answer / false RESOLVED (wrong or incomplete answer) /
    incorrect abstention
  - non-answerable needs: correct abstention / overclaim (resolved anyway)
  - evidence contamination (verified value outside the expected set) is reported
    separately from conclusion contamination (the final answer is wrong/overclaimed),
    including "correct answer despite wrong evidence".

Full material stays outside the repo (see blindtest_v3_material.json). The committed
fixture/eval are redacted: no contract text, only ids, types, counts, hashes, choices.

Run: backend/.venv/bin/python crates/swe-gym/tools/blindtest_v3_chain.py
"""

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import blindtest_v2_arms as base  # noqa: E402
import blindtest_v2_arms_m3_m4 as m3m4  # noqa: E402
import blindtest_v2_arms_m6 as m6  # noqa: E402

REPO = base.REPO
MAT = Path.home() / "blindtest-v3-material"
B = base.B
contract = base.contract
FIXTURE = B / "jev_span_fixtures_v3.json"
EVAL_OUT = B / "blindtest_v3_chain_eval.json"
CANDIDATES_REDACTED = B / "blindtest_v3_candidates_redacted.json"
RECOVERY_VERSION = m6.RECOVERY_VERSION


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def env_value(name: str, fallback: str = "") -> str:
    return base.env_value(name, REPO / "backend" / ".env", fallback)


class JevRecorder:
    """Frozen v3 answers, keyed by the whole assessment task."""

    def __init__(self, api_key, base_url, model):
        self.api_key, self.base, self.model = api_key, base_url, model
        self.store = {}
        self.new_calls = 0
        self.total_calls = 0
        if FIXTURE.exists():
            for entry in json.load(open(FIXTURE, encoding="utf-8")).get("entries", []):
                self.store[(entry["case_id"], entry["span_canon_sha256"],
                            entry["prompt_version"], entry["context_sha256"])] = entry["choice"]

    def verify(self, case_id, context, span, need_type):
        question = contract.verification_question(need_type, span)
        version = question["prompt_version"]
        return self._ask(case_id, context, span, version, question["question"])

    def recovery(self, case_id, context, span, need_type, role):
        version = RECOVERY_VERSION
        return self._ask(case_id, context, span, version,
                         m6.recovery_question(need_type, role, span))

    def _ask(self, case_id, context, span, version, question):
        self.total_calls += 1
        key = (case_id, sha(base.normalize(span)), version, sha(context))
        if key in self.store:
            return self.store[key]
        body = json.dumps({"model": self.model, "state": {"text": context},
                           "questions": question}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/v1/systemone", data=body, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        choice = str(payload["answers"]["evidence"].get("choice") or "").upper()
        if choice not in {"YES", "NO", "UNCERTAIN"}:
            raise SystemExit(f"ogiltigt Jev-svar: {payload!r}")
        self.store[key] = choice
        self.new_calls += 1
        return choice

    def save(self):
        entries = [
            {"key": sha(f"{k[0]}\u0000{k[1]}\u0000{k[2]}\u0000{k[3]}")[:16],
             "case_id": k[0], "span_canon_sha256": k[1], "prompt_version": k[2],
             "context_sha256": k[3], "model": self.model, "choice": v}
            for k, v in self.store.items()
        ]
        json.dump({"version": 1, "redacted": True,
                   "redaction_note": "v3 answers keyed by case + span digest + prompt version + context digest; no contract text.",
                   "entries": sorted(entries, key=lambda e: e["key"])},
                  open(FIXTURE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def run_arm(cases, candidates, docs, recorder, *, chain):
    states, details = {}, {}
    new_before, total_before = recorder.new_calls, recorder.total_calls
    use_m1 = chain == "m1m6"
    use_m2 = use_m1
    use_m3 = use_m1
    use_m4 = use_m1
    use_m6 = use_m1
    for case in cases:
        cid = case["case_id"]
        need = case["needs"][0]
        clause = case["clause"]
        need_role = need.get("role") or ""
        cardinality = need.get("cardinality") or "SINGLE"
        context, win_stats = (
            m3m4.structural_window(case, docs[case["document"]])
            if (use_m4 and need["type"] == "PARTY")
            else (clause, {"expanded": False, "reason": "M4 not in arm"})
        )
        gold_values = {
            base.canon_value(base.presentation(g["span"]) if use_m1 else g["span"])
            for g in case["gold"]
        }
        cands = sorted(candidates.get(cid, []))
        if use_m2:
            cands, _ = base.consolidate(cands, [g["span"] for g in case["gold"]])
        cand_hashes = {sha(base.normalize(c)) for c in cands}
        ordered = []
        seen = set()
        for span in cands:
            key = sha(base.normalize(span))
            if key in seen:
                continue
            seen.add(key)
            ordered.append(span)
        verdicts = []
        recovery_events = []
        for original in ordered:
            presented = base.presentation(original) if use_m1 else original
            choice = recorder.verify(cid, context, presented, need["type"])
            role = m3m4.role_for(presented, context, need_role, m3=use_m3)
            is_candidate = sha(base.normalize(original)) in cand_hashes
            if use_m6 and is_candidate and choice == "NO":
                detector = m6.deterministic_value(need["type"], presented)
                role_match = not need_role or role is None or role == need_role
                if detector and role_match:
                    supplementary = recorder.recovery(cid, context, presented, need["type"], need_role)
                    recovered = supplementary == "YES"
                    recovery_events.append({
                        "span_sha256": sha(base.normalize(presented)),
                        "detector": True, "role_match": True,
                        "first_choice": "NO", "supplementary_choice": supplementary,
                        "recovered": recovered,
                        "recovered_value_in_gold": recovered and base.canon_value(presented) in gold_values,
                    })
                    if recovered:
                        choice = "YES"
            verdicts.append(contract.SpanVerdict(
                span=presented, need_type=need["type"],
                prompt_version=contract.verification_question(need["type"], presented)["prompt_version"],
                choice=choice, unit_id=cid, unit_text=context, role=role, role_locked=True))
        findings = contract.derive_findings(verdicts, need_type=need["type"], need_role=need_role)
        contract_state, verified, wrong = base.outcome(findings, gold_values)
        approved = sorted({
            base.canon_value(v.span) for v in verdicts
            if v.choice == "YES" and (not need_role or v.role is None or v.role == need_role)
        })
        if use_m1 and cardinality == "MULTIPLE_UNKNOWN":
            # Values alone never establish completeness: the frozen M5 policy.
            # M0 has no cardinality model, so it keeps the original contract outcome.
            state = "incomplete_unknown_cardinality"
        else:
            state = contract_state
        details[cid] = {
            "state": state,
            "contract_state": contract_state,
            "approved_value_sha256": [sha(v) for v in approved],
            "gold_value_sha256": sorted(sha(v) for v in gold_values),
            "recovery_events": recovery_events,
            "m4_window": win_stats if use_m4 else None,
        }
        states[cid] = state
    return states, details, {"execution_jev_calls": recorder.total_calls - total_before,
                             "experiment_new_calls": recorder.new_calls - new_before}


def score(case, detail):
    expected = set(detail["gold_value_sha256"])
    approved = set(detail["approved_value_sha256"])
    state = detail["state"]
    answerable = case["answer_facit"]["answerable"]
    resolved = state == "resolved"
    evidence_contamination = approved - expected
    correct_answer = False
    false_resolved = False
    overclaim = False
    correct_abstention = False
    incorrect_abstention = False
    if answerable:
        if resolved and approved == expected:
            correct_answer = True
        elif resolved:
            false_resolved = True
        else:
            incorrect_abstention = True
    else:
        if resolved:
            overclaim = True
            false_resolved = True
        else:
            correct_abstention = True
    return {
        "resolved": resolved,
        "correct_answer": correct_answer,
        "false_resolved": false_resolved,
        "overclaim": overclaim,
        "correct_abstention": correct_abstention,
        "incorrect_abstention": incorrect_abstention,
        "evidence_contamination": bool(evidence_contamination),
        "answer_contamination": resolved and bool(evidence_contamination),
        "correct_answer_despite_wrong_evidence": correct_answer and bool(evidence_contamination),
    }


def main():
    facit = json.load(open(MAT / "private" / "facit_v3.full.json", encoding="utf-8"))
    candidates = json.load(open(MAT / "private" / "candidates_v3.full.json", encoding="utf-8"))
    docs = {p.stem: p.read_text(encoding="utf-8") for p in MAT.glob("*.txt")}
    cases = facit["cases"]
    api_key = env_value("TYPESAFE_API_KEY")
    base_url = env_value("TYPESAFE_BASE_URL", "https://api.typesafe.ai")
    model = env_value("JEV_MODEL", "jev-latest")
    recorder = JevRecorder(api_key, base_url, model)

    arms = {"m0": "m0", "m1m6": "m1m6"}
    states_all, details_all, costs = {}, {}, {}
    for key, chain in arms.items():
        states, details, cost = run_arm(cases, candidates, docs, recorder, chain=chain)
        states_all[key], details_all[key], costs[key] = states, details, cost
        print(f"{key}: resolved {sum(1 for s in states.values() if s == 'resolved')}/{len(cases)}"
              f", JEV {cost['execution_jev_calls']} (new {cost['experiment_new_calls']})")

    scored = {}
    per_case = []
    for key in arms:
        rows = []
        for case in cases:
            row = score(case, details_all[key][case["case_id"]])
            row["case_id"] = case["case_id"]
            row["need_type"] = case["needs"][0]["type"]
            row["cardinality"] = case["needs"][0].get("cardinality", "SINGLE")
            row["answerable"] = case["answer_facit"]["answerable"]
            rows.append(row)
        scored[key] = rows
        per_case.append({
            "case_id": None,  # replaced below per case
        })
    per_case = []
    for case in cases:
        cid = case["case_id"]
        per_case.append({
            "case_id": cid,
            "document": case["document"],
            "need_type": case["needs"][0]["type"],
            "cardinality": case["needs"][0].get("cardinality", "SINGLE"),
            "answerable": case["answer_facit"]["answerable"],
            "states": {key: states_all[key][cid] for key in arms},
            "d10": {key: {k: v for k, v in score(case, details_all[key][cid]).items() if k != "case_id"}
                    for key in arms},
        })

    def agg(key):
        rows = scored[key]
        return {
            "cases": len(rows),
            "resolved": sum(1 for r in rows if r["resolved"]),
            "correct_answers": sum(1 for r in rows if r["correct_answer"]),
            "correct_abstentions": sum(1 for r in rows if r["correct_abstention"]),
            "incorrect_abstentions": sum(1 for r in rows if r["incorrect_abstention"]),
            "false_resolved": sum(1 for r in rows if r["false_resolved"]),
            "overclaims_non_answerable": sum(1 for r in rows if r["overclaim"]),
            "evidence_contamination_cases": sum(1 for r in rows if r["evidence_contamination"]),
            "answer_contamination_cases": sum(1 for r in rows if r["answer_contamination"]),
            "correct_answer_despite_wrong_evidence": sum(
                1 for r in rows if r["correct_answer_despite_wrong_evidence"]),
        }

    regressions = [
        {"case_id": case["case_id"], "m0": details_all["m0"][case["case_id"]]["state"],
         "m1m6": details_all["m1m6"][case["case_id"]]["state"]}
        for case in cases
        if score(case, details_all["m0"][case["case_id"]])["correct_answer"]
        and not score(case, details_all["m1m6"][case["case_id"]])["correct_answer"]
    ]
    gains = [
        {"case_id": case["case_id"], "m0": details_all["m0"][case["case_id"]]["state"],
         "m1m6": details_all["m1m6"][case["case_id"]]["state"]}
        for case in cases
        if score(case, details_all["m1m6"][case["case_id"]])["correct_answer"]
        and not score(case, details_all["m0"][case["case_id"]])["correct_answer"]
    ]

    eval_out = {
        "version": 1,
        "name": "blindtest-v3-chain",
        "redacted": True,
        "redaction_note": ("Blindtest v3 result: no contract text; case ids, types, cardinalities, "
                           "states, D10 classes, counts and hashes only."),
        "frozen_material": "crates/swe-gym/benchmarks/blindtest_v3_material.json",
        "frozen_chain": "crates/swe-gym/benchmarks/gliner2_chain_frozen_v2.json",
        "arms": {"m0": "frozen original chain (no M1-M6)",
                 "m1m6": "frozen M1-M6 chain (manifest gliner2-chain-m1m6-v1)"},
        "metrics": {key: agg(key) for key in arms},
        "d10": {
            "definition": ("Evidence contamination: a verified value outside the expected set. "
                           "Answer contamination: a resolved answer containing such a value. "
                           "Non-answerable needs: correct abstention vs overclaim (resolved anyway)."),
            "correct_answer_despite_wrong_evidence": "reported per arm and case",
        },
        "costs": {key: {**costs[key], "gliner_inferences_shared": 13} for key in arms},
        "gains_m1m6": gains,
        "regressions_m1m6": regressions,
        "per_case": per_case,
        "details": details_all,
        "reservation": ("One frozen run, no adjustments. Both arms are scored against exactly the "
                        "same facit. This is the generalization test for the frozen M1-M6 chain; "
                        "single-run results on 13 needs are evidence, not a production guarantee."),
    }
    json.dump(eval_out, open(EVAL_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump({"redacted": True, "candidates_canon_sha256": {
        cid: [sha(s) for s in spans] for cid, spans in candidates.items()}},
        open(CANDIDATES_REDACTED, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    recorder.save()
    print("\nmetrics:", json.dumps({key: agg(key) for key in arms}, ensure_ascii=False))
    print("\nper fall (M0 -> M1-M6):")
    for row in per_case:
        print(f"  {row['case_id']}: {row['states']['m0']} -> {row['states']['m1m6']}"
              f" | answerable={row['answerable']}")
    print("\ngains:", [g["case_id"] for g in gains], "| regressions:", [r["case_id"] for r in regressions])
    print(f"Jev: {recorder.total_calls} execution, {recorder.new_calls} nya")


if __name__ == "__main__":
    main()

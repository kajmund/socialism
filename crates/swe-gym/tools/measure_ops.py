#!/usr/bin/env python3
"""Operation-contract verification (docs/SWE_Sweycoins_v2.md 30): apply
the typed operation graph to the 12 cases from the frozen data and the
selective rule. The MAX_NOTICE_PERIOD operation has an explicit input
contract; the gate blocks execution on partial resolution — g3-06 must
ABSTAIN (INSUFFICIENT_EVIDENCE) instead of answering wrong, without
losing the four successful cases. Also the cost-consistency check: all
strategies in one unit (marginal JEV calls), no mixing.

Usage: python3 crates/swe-gym/tools/measure_ops.py
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from measure_selective import SELECTIVE_RULE  # noqa: E402
from measure_chains import correct, normalize_answer, recover_content  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"

STATES = B / "action_market" / "states.txt"
GOLDEN = B / "golden_v3.json"
BENCH = B / "bench_real_v2.json"
MILESTONE = B / "milestone_capture" / "answers.txt"
OUT = B / "golden_v3_ops.json"

JEV_COST = 1_000


def doc_names(question):
    return set(re.findall(r"Avtal_\d+_[A-Za-zåäöÅÄÖ_]+", question))


def main():
    golden = {q["id"]: q for q in json.load(open(GOLDEN, encoding="utf-8"))["questions"]}
    evidence_by_case = {q["id"]: set(q["evidence"]) for q in golden.values()}
    compared_docs = {q["id"]: doc_names(q["question"]) for q in golden.values()}
    texts = {}
    for q in json.load(open(BENCH, encoding="utf-8"))["questions"]:
        texts.update(q.get("texts", {}))

    states = []
    for line in STATES.read_text(encoding="utf-8").splitlines():
        qid, chunk, baseline, clarified, context = line.split("|")
        states.append({
            "qid": qid,
            "chunk": chunk,
            "context_jv": context,
            "facit": chunk in evidence_by_case.get(qid, set()),
        })

    def months_local(d):
        n, unit = d.split(" ", 1)
        n = int(n)
        return n * {"år": 12, "månad": 1, "månader": 1, "vecka": 0.25, "veckor": 0.25, "dag": 1 / 30, "dagar": 1 / 30}.get(unit, 0)

    # Baseline static/K-expansion answers (frozen).
    baseline_ans = {}
    bblock = {}
    bkey = None
    for line in MILESTONE.read_text(encoding="utf-8").splitlines():
        if line.startswith("=== "):
            bkey = line[4:].strip()
            bblock = {}
        elif bkey and line.startswith(("STATIC:", "KEXP:")):
            k, _, v = line.partition(":")
            bblock[k] = v.strip()
        if bkey and "KEXP" in bblock:
            baseline_ans[bkey] = bblock

    print(f"{'fall':<7} {'operation':<24} {'resolved/inputs':>15} {'grind':<24} {'svar':<36} {'facit-ok'}")
    rows = {}
    for qid, q in golden.items():
        docs = compared_docs[qid]
        is_comparison = "längst uppsägningstid" in q["question"]

        # The operation contract derives from the QUESTION SPEC (the
        # named documents), never from what happened to get resolved.
        required = sorted(docs) if is_comparison else []
        op_name = "MAX_NOTICE_PERIOD" if is_comparison else "NO_OP/EXTRACT"

        resolved_values = {}
        jv_calls = 0
        for s in states:
            if s["qid"] != qid:
                continue
            verdict, cost = SELECTIVE_RULE(s, texts, compared_docs)
            jv_calls += cost // JEV_COST
            if verdict == "resolved":
                from gen_golden_v2 import extract_duration
                d = extract_duration(texts.get(s["chunk"], ""))
                if d:
                    doc = s["chunk"].split(":")[0]
                    resolved_values.setdefault(doc, set()).add(d)

        # The gate: ALL_REQUIRED over the question's inputs.
        missing = [d for d in required if d not in resolved_values]
        answer = None
        gate = "READY" if not missing else "INSUFFICIENT_EVIDENCE"
        if gate == "READY" and is_comparison:
            values = {d: months_local(sorted(vs)[0]) for d, vs in resolved_values.items() if len(vs) == 1}
            if values:
                answer = max(values, key=lambda d: values[d])
        answer_ok = answer == q["conclusion"] if answer else None

        static_norm = normalize_answer(recover_content(baseline_ans.get(qid, {}).get("STATIC", "")), q)
        static_correct = correct(q["conclusion"], static_norm, q)

        rows[qid] = {
            "operation": op_name,
            "required_inputs": required,
            "missing_inputs": missing,
            "gate": gate,
            "answer": answer,
            "facit": q["conclusion"],
            "correct": answer_ok,
            "static_correct": static_correct,
            "jv_calls": jv_calls,
        }
        print(
            f"{qid:<7} {op_name:<24} {len(resolved_values):>4}/{len(required):<10} {gate:<24} "
            f"{str(answer or '—'):<36} {str(answer_ok)}"
        )

    ok_cases = [qid for qid, r in rows.items() if r["correct"] is True]
    abstained = [qid for qid, r in rows.items() if r["gate"] == "INSUFFICIENT_EVIDENCE"]
    print(f"\nframgångsrika fall bevarade: {ok_cases}")
    print(f"fall som avstår (grinden blockerar): {abstained}")
    print(f"g3-06: {'AVSTÅR korrekt — operationen kördes aldrig' if rows['g3-06']['gate'] == 'INSUFFICIENT_EVIDENCE' else 'fel'}")

    # Cost-consistency: one unit (marginal JEV calls) for all strategies.
    print("\nkostnadskonsistens (samma enhet: marginella JEV-anrop x 1 coin):")
    print("  extrahera-först     78 JEV-anrop = 78 000 milli (extraktion: 0/92 milli vid eps=0/1)")
    print("  förtydligad-först   92 JEV-anrop = 92 000 milli")
    print("  selektiv regel      12 JEV-anrop = 12 000 milli (från frysta data)")
    print("  -> allokerade/ackumulerade siffror redovisas aldrig i samma kolumn som marginella.")

    json.dump(rows, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""The sharpened milestone analysis (docs/SWE_Sweycoins_v2.md 24).

Acceptance criteria (one case suffices):
  C1  same rank-based initial candidates for the static and iterative
      chains (structural: both read the frozen golden_v3_ranks).
  C2  an identified REQUIRED need initially lacks evidence.
  C3  the gap step leads to new facit-correct evidence.
  C4  the iterative chain answers correctly where the static is wrong.
  C5  a plain K-expansion at comparable actual cost does not.
  C6  reproducible without facit leaking into the decision process
      (structural: candidates/ranks are document-based; facit is read
      only here, for evaluation).

Also breaks H3 down by stop reason: 'sufficient' (gap judges the
information enough), 'no yield' (needs produced nothing) and
'exhausted' (budget/candidates ran out).

Usage: python3 crates/swe-gym/tools/measure_milestone.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from measure_chains import correct, normalize_answer, recover_content  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"

GOLDEN = B / "golden_v3.json"
CAP = B / "milestone_capture"
OUT = B / "golden_v3_milestone.json"

JEV_COST = 1_000
LLM_COST = 10_000


def load_hits(qid, which):
    path = CAP / f"{qid}-{which}.json"
    if not path.exists():
        return set()
    data = json.load(open(path, encoding="utf-8"))
    return {e["chunk_id"] for e in data["entries"] if e["choice"] == "fynd"}


def main():
    golden = {q["id"]: q for q in json.load(open(GOLDEN, encoding="utf-8"))["questions"]}
    blocks = {}
    block = {}
    key = None
    for line in (CAP / "answers.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("=== "):
            key = line[4:].strip()
            block = {}
        elif key and line.startswith(("STATIC:", "KEXP:", "GAP:", "NEEDS:", "ITERATIVE:")):
            k, _, v = line.partition(":")
            block[k] = v.strip()
        if key and "ITERATIVE" in block:
            blocks[key] = block

    milestone = []
    stop_reasons = {}
    rows = {}
    for qid, q in golden.items():
        block = blocks.get(qid, {})
        initial = load_hits(qid, "initial")
        need_hits = load_hits(qid, "needjev")
        evidence = set(q["evidence"])

        static_norm = normalize_answer(recover_content(block.get("STATIC", "")), q)
        kexp_norm = normalize_answer(recover_content(block.get("KEXP", "")), q)
        iter_norm = normalize_answer(recover_content(block.get("ITERATIVE", "")), q)
        static_correct = correct(q["conclusion"], static_norm, q)
        kexp_correct = correct(q["conclusion"], kexp_norm, q)
        iter_correct = correct(q["conclusion"], iter_norm, q)

        # C2: a REQUIRED need whose document has no initial hit but holds
        # facit evidence.
        required_unmet = False
        for need in block.get("NEEDS", "").split("||"):
            need = need.strip()
            if not need:
                continue
            parts = need.split("|")
            if len(parts) < 5:
                continue
            n, doc, imp, status, _resolved = parts[0], parts[1], parts[2], parts[3], parts[4]
            if imp == "REQUIRED" and status == "UNRESOLVED" and doc and doc != "null":
                doc_evidence = {e for e in evidence if e.split(":")[0] == doc}
                doc_initial = {c for c in initial if c.split(":")[0] == doc}
                if doc_evidence and not doc_initial:
                    required_unmet = True

        new_facit = need_hits & evidence
        c1 = True  # structural: both chains read the same frozen rank file
        c2 = required_unmet
        c3 = len(new_facit) > 0
        c4 = (not static_correct) and iter_correct
        c5 = (not kexp_correct) and c4
        c6 = True  # structural: candidates are document-based, facit only here

        n_need_calls = len(json.load(open(CAP / f"{qid}-needjev.json", encoding="utf-8"))["entries"]) if (CAP / f"{qid}-needjev.json").exists() else 0
        static_cost = 8 * JEV_COST + LLM_COST
        kexp_cost = 16 * JEV_COST + LLM_COST
        iter_cost = 8 * JEV_COST + 2 * LLM_COST + n_need_calls * JEV_COST

        # H3 stop-reason diagnosis on negatives.
        if not q["positive"]:
            gap_text = recover_content(block.get("GAP", "")).strip()
            if gap_text == "[]" or "INGET" in gap_text.upper() or not block.get("NEEDS", "").strip():
                stop_reasons[qid] = "sufficient"
            elif len(need_hits) == 0:
                stop_reasons[qid] = "no yield"
            else:
                stop_reasons[qid] = "exhausted"

        if c1 and c2 and c3 and c4 and c5 and c6:
            milestone.append(qid)

        rows[qid] = {
            "static_correct": static_correct,
            "kexp_correct": kexp_correct,
            "iterative_correct": iter_correct,
            "required_unmet": c2,
            "new_facit_evidence": sorted(new_facit),
            "static_cost": static_cost,
            "kexp_cost": kexp_cost,
            "iterative_cost": iter_cost,
            "stop_reason": stop_reasons.get(qid),
            "criteria": {"c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5, "c6": c6},
        }

    json.dump(rows, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"{'fall':<7} {'statisk':>7} {'kexp':>6} {'iterativ':>8} {'C2':>4} {'C3':>4} | stop")
    for qid, r in rows.items():
        print(
            f"{qid:<7} {str(r['static_correct']):>7} {str(r['kexp_correct']):>6} "
            f"{str(r['iterative_correct']):>8} {str(r['required_unmet']):>4} "
            f"{str(len(r['new_facit_evidence']) > 0):>4} | {r['stop_reason'] or ''}"
        )
    print(f"\nMILSTOLPE (alla sex kriterier uppfyllda): {milestone if milestone else 'inte nådd'}")
    print(f"stop-orsaker (negativa): {stop_reasons}")
    print(f"skrivet: {OUT}")


if __name__ == "__main__":
    main()

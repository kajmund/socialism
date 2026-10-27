#!/usr/bin/env python3
"""Variant comparison (docs/SWE_Sweycoins_v2.md 22): static vs iterative vs
adaptive chains plus the oracle synthesis test, with information gain,
coverage delta and correctness as SEPARATE signals.

Usage: python3 crates/swe-gym/tools/measure_variants.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from measure_chains import correct, normalize_answer, recover_content  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"

GOLDEN = B / "golden_v2.json"
FIX = B / "golden_v2_fixtures"
CAP = B / "variant_capture"
OUT = B / "golden_v2_variants.json"

QUESTIONS = ["g2-15", "g2-17", "g2-29", "g2-20", "g2-23"]

JEV_COST = 1_000
LLM_COST = 10_000


def load_hits(qid, provider):
    data = json.load(open(FIX / f"{qid}-{provider}.json", encoding="utf-8"))
    return {e["chunk_id"] for e in data["entries"] if e["choice"] == "fynd"}


def load_new_hits(qid):
    path = CAP / f"{qid}-newjev.json"
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
        elif key and line.startswith(("GAP:", "NEW_HITS:", "STATIC:", "ITERATIVE:", "ADAPTIVE:", "ORACLE:")):
            k, _, v = line.partition(":")
            block[k] = v.strip()
        if key and "ORACLE" in block:
            blocks[key] = block

    results = {}
    for qid in QUESTIONS:
        q = golden[qid]
        initial = load_hits(qid, "jev")
        new = load_new_hits(qid)
        block = blocks[qid]
        n_initial = len(json.load(open(FIX / f"{qid}-jev.json", encoding="utf-8"))["entries"])
        n_new = len(json.load(open(CAP / f"{qid}-newjev.json", encoding="utf-8"))["entries"])

        evidence = set(q["evidence"])
        initial_cov = len(initial & evidence) / max(1, len(evidence))
        final_cov = len((initial | new) & evidence) / max(1, len(evidence))
        info_gain = len(new & evidence)  # the gap step's unique contribution

        variants = {}
        for name, field in [("static", "STATIC"), ("iterative", "ITERATIVE"), ("adaptive", "ADAPTIVE")]:
            norm = normalize_answer(recover_content(block.get(field, "")), q)
            variants[name] = {
                "correct": correct(q["conclusion"], norm, q),
                "conclusion": norm,
            }
        oracle_norm = normalize_answer(recover_content(block.get("ORACLE", "")), q)
        oracle_correct = correct(q["conclusion"], oracle_norm, q)

        # Costs: same primitives, actual per-chain totals.
        variants["static"]["cost"] = n_initial * JEV_COST + LLM_COST
        variants["iterative"]["cost"] = n_initial * JEV_COST + 2 * LLM_COST + n_new * JEV_COST
        variants["adaptive"]["cost"] = n_initial * JEV_COST + 8 * JEV_COST + LLM_COST
        variants["static"]["coverage"] = initial_cov
        variants["iterative"]["coverage"] = final_cov
        variants["adaptive"]["coverage"] = final_cov
        variants["iterative"]["info_gain"] = info_gain
        variants["adaptive"]["info_gain"] = info_gain

        results[qid] = {
            "question": q["question"],
            "facit": q["conclusion"],
            "initial_coverage": round(initial_cov, 3),
            "final_coverage": round(final_cov, 3),
            "info_gain": info_gain,
            "oracle_synthesis_correct": oracle_correct,
            "oracle_conclusion": oracle_norm,
            "variants": variants,
        }

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"{'fråga':<8} {'init.cov':>8} {'final.cov':>9} {'info':>4} {'orakel':>6} | {'statisk':>7} {'iterativ':>8} {'adaptiv':>7}")
    for qid, r in results.items():
        print(
            f"{qid:<8} {r['initial_coverage']:>8.2f} {r['final_coverage']:>9.2f} {r['info_gain']:>4} "
            f"{str(r['oracle_synthesis_correct']):>6} | "
            f"{str(r['variants']['static']['correct']):>7} "
            f"{str(r['variants']['iterative']['correct']):>8} "
            f"{str(r['variants']['adaptive']['correct']):>7}"
        )
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()

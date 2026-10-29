#!/usr/bin/env python3
"""Dependency-case hypotheses (docs/SWE_Sweycoins_v2.md 23):
H1 — the gap analysis discovers a necessary information need the first
retrieval missed (new facit evidence found after the gap).
H2 — the new finding changes the CONCLUSION's correctness, not just
coverage (static wrong -> iterative right).
H3 — on negative controls the chain recognizes that further
investigation is not worth the cost (gap says INGET / adds nothing).
Plus the milestone: at least one reproducible case where the iterative
chain answers correctly and the static chain does not.

Usage: python3 crates/swe-gym/tools/measure_dependencies.py
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from measure_chains import correct, normalize_answer, recover_content  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"

GOLDEN = B / "golden_v3.json"
CAP = B / "dependency_capture"
OUT = B / "golden_v3_dependencies.json"


def load_hits(qid, provider):
    path = CAP / f"{qid}-{provider}.json"
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
        elif key and line.startswith(("STATIC:", "GAP:", "NEW_HITS:", "ITERATIVE:")):
            k, _, v = line.partition(":")
            block[k] = v.strip()
        if key and "ITERATIVE" in block:
            blocks[key] = block

    results = {}
    h1 = h2 = h3 = 0
    milestone = []
    for qid, q in golden.items():
        block = blocks.get(qid, {})
        initial = load_hits(qid, "jev")
        new = load_hits(qid, "newjev")
        evidence = set(q["evidence"])
        new_facit = new & evidence
        gap_says_nothing = "INGET" in recover_content(block.get("GAP", "")).upper()

        static_norm = normalize_answer(recover_content(block.get("STATIC", "")), q)
        iter_norm = normalize_answer(recover_content(block.get("ITERATIVE", "")), q)
        static_correct = correct(q["conclusion"], static_norm, q)
        iter_correct = correct(q["conclusion"], iter_norm, q)

        h1_yes = len(new_facit) > 0
        h2_yes = (not static_correct) and iter_correct
        h3_yes = (not q["positive"]) and (gap_says_nothing or len(new) == 0)
        h1 += h1_yes
        h2 += h2_yes
        h3 += h3_yes
        if h2_yes:
            milestone.append(qid)

        results[qid] = {
            "question": q["question"],
            "positive": q["positive"],
            "static_correct": static_correct,
            "iterative_correct": iter_correct,
            "new_facit_evidence": sorted(new_facit),
            "gap_says_nothing": gap_says_nothing,
            "h1": h1_yes,
            "h2": h2_yes,
            "h3": h3_yes,
        }

    positives = [r for r in results.values() if r["positive"]]
    negatives = [r for r in results.values() if not r["positive"]]
    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"H1 (gap upptäckte nytt facit-evidens): {h1}/{len(positives)} positiva fall")
    print(f"H2 (statisk fel -> iterativ rätt): {h2}/{len(positives)} positiva fall")
    print(f"H3 (negativ: kedjan slutade i tid): {h3}/{len(negatives)} negativa fall")
    print(f"milstolpe (>=1 fall där kedjan ensam svarar rätt): {milestone}")
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()

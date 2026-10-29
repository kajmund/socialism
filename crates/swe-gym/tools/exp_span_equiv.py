#!/usr/bin/env python3
"""Span-equivalence experiment (isolated, own version): does a deterministic
canonical-value layer remove the span-boundary artifacts from blindtest v1?

Canonical value (never changes the frozen span or the JEV verdicts — applied
post-hoc to the frozen spans for comparison and competing-value dedup):
  - brackets removed, whitespace collapsed (frozen rule)
  - leading grammatical words stripped from a closed list
    {inom, i, under, senast, den, det, de, en, ett}
    (quantifiers like minst/högst/cirka are deliberately NOT stripped —
    they carry semantic load)
  - unit genitive normalized: dagars->dagar, veckors->veckor,
    månaders->månader, års->år, timmars->timmar

No model calls. Re-evaluates the frozen per-case verdicts with canonical
values and reports which verdicts flip.

Run: python3 crates/swe-gym/tools/exp_span_equiv.py
"""

import json
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
EVAL = json.load(open(B / "blindtest_facit_v1_eval.json", encoding="utf-8"))

LEADING = {"inom", "i", "under", "senast", "den", "det", "de", "en", "ett"}
GENITIVE = {"dagars": "dagar", "veckors": "veckor", "månaders": "månader",
            "års": "år", "timmars": "timmar"}


def canon(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\[\]]", "", s)).strip().lower()


def canon_value(s: str) -> str:
    words = canon(s).split()
    while words and words[0] in LEADING:
        words = words[1:]
    words = [GENITIVE.get(w, w) for w in words]
    return " ".join(words)


def re_verdict(r):
    gold = {canon_value(g) for g in r["gold"]}
    extracted = {canon_value(s) for s in r["extracted_same_type"]}
    approved = {canon_value(s) for s in r["approved"]}
    glin = {canon_value(s) for s in r["gliner_candidates"]}
    competing = {s for s in approved if s in glin and s not in gold}
    competing |= {s for s in extracted if s not in gold}
    resolved = bool(gold) and all(g in approved or g in extracted for g in gold)
    if resolved and len(competing) >= 2:
        return "ambiguous", competing
    if resolved:
        return "resolved", competing
    if len(competing) >= 2:
        return "ambiguous", competing
    if competing:
        return "false_resolved", competing
    return "unsolved", competing


def main():
    rows = []
    flips = []
    for r in EVAL["per_case"]:
        new, competing = re_verdict(r)
        old = r["verdict"]
        rows.append({"case_id": r["case_id"], "verdict": new,
                     "old_verdict": old, "competing": sorted(competing)})
        if new != old:
            flips.append(f"{r['case_id']}: {old} -> {new}")
    print("Spannekvivalens — omvärdering av de frusna 20 fallen (inga modellanrop)\n")
    for f in flips:
        print("  FLIP:", f)
    if not flips:
        print("  inga flippar")
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print("\nny fördelning:", counts)
    out = B / "blindtest_span_v1.json"
    json.dump({"version": 1, "canonical_rule": {
                   "leading_stripped": sorted(LEADING),
                   "genitive_normalized": GENITIVE,
               }, "rows": rows, "flips": flips},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"skrivet: {out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""D10 v3 — answer-level replay with E1 (dates) + E2 (span equivalence) +
E3 (operational-role check), classified against the frozen D10 table and
compared to D10 v2.

Run: python3 crates/swe-gym/tools/replay_d10_v3.py
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
E3 = json.load(open(B / "blindtest_e3_v1.json", encoding="utf-8"))
D10F = json.load(open(B / "blindtest_d10_facit_v1.json", encoding="utf-8"))
V2 = {r["case_id"]: r for r in
      json.load(open(B / "blindtest_d10_v2.json", encoding="utf-8"))["rows"]}

# Factually-the-same-value competing spans that canonical-value does not
# merge (abbreviation, plural-definite, content-word boundary) — annotated.
VARIANT_CASES = {"bt-05": "nkk = party abbreviation",
                 "bt-10": "Semester 30 dagar = same fact, boundary",
                 "bt-13": "12 m å naderna = same fact, plural-definite"}


def main():
    rows, flips = [], []
    for r in E3["rows"]:
        cid = r["case_id"]
        verdict = r["verdict"]
        af = D10F["cases"][cid]
        if verdict == "resolved":
            if r["competing"] and cid not in VARIANT_CASES:
                klass = "correct_answer_despite_wrong_evidence"
            elif r["competing"]:
                klass = "correct_answer_boundary_variant"
            else:
                klass = "correct_answer"
        elif verdict == "false_resolved":
            klass = "contaminated_answer"
        elif verdict == "ambiguous":
            klass = "correct_abstention"
        else:
            klass = ("correct_abstention_external_need" if not af["answerable"]
                     else "incorrect_abstention")
        rows.append({"case_id": cid, "class": klass,
                     "competing": r["competing"],
                     "note": VARIANT_CASES.get(cid, "")})
        old = V2[cid]["class"]
        if old != klass:
            flips.append(f"{cid}: {old} -> {klass}")

    counts = {}
    for r in rows:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    print("D10 v3 — E1+E2+E3, mot D10 v2-tabellen\n")
    for f in flips:
        print("  FLIP:", f)
    if not flips:
        print("  inga klassflippar")
    print()
    for k in ["correct_answer", "correct_answer_boundary_variant",
              "correct_abstention", "correct_abstention_external_need",
              "incorrect_abstention", "contaminated_answer",
              "correct_answer_despite_wrong_evidence"]:
        n = counts.get(k, 0)
        if n:
            print(f"  {k:<42} {n}")
    print()
    print(f"felaktiga avståenden: {counts.get('incorrect_abstention', 0)}")
    print(f"kontaminerade svar: {counts.get('contaminated_answer', 0)}")
    print(f"dold evidensrisk: "
          f"{counts.get('correct_answer_despite_wrong_evidence', 0)}")
    # Regression controls from the user's D10 v3 criteria.
    for cid in ["bt-02", "bt-03", "bt-06", "bt-17"]:
        print(f"  kontroll {cid}: {V2[cid]['class']} -> "
              f"{next(r['class'] for r in rows if r['case_id'] == cid)}")
    out = B / "blindtest_d10_v3.json"
    json.dump({"version": 3, "counts": counts, "rows": rows, "flips": flips},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nskrivet: {out}")


if __name__ == "__main__":
    main()

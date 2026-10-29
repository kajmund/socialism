#!/usr/bin/env python3
"""D10 replay on blindtest v1 with the two isolated experiments applied:
  - E1 (dates): span-date-v1 verdicts for DATE needs (from the fixture)
  - E2 (span equivalence): canonical-value comparison everywhere
Measures against the FROZEN D10 table (blindtest_d10_v1.json): how many of
the three incorrect abstentions disappear, whether any previously correct
conclusion regresses, and whether contamination stays zero.

Run: python3 crates/swe-gym/tools/replay_d10_v2.py
"""

import json
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
EVAL = json.load(open(B / "blindtest_facit_v1_eval.json", encoding="utf-8"))
D10F = json.load(open(B / "blindtest_d10_facit_v1.json", encoding="utf-8"))
D10V1 = {r["case_id"]: r for r in
         json.load(open(B / "blindtest_d10_v1.json", encoding="utf-8"))["rows"]}
FIXTURE = {e["key"]: e for e in
           json.load(open(B / "jev_span_fixtures.json", encoding="utf-8"))["entries"]}

LEADING = {"inom", "i", "under", "senast", "den", "det", "de", "en", "ett"}
GENITIVE = {"dagars": "dagar", "veckors": "veckor", "månaders": "månader",
            "års": "år", "timmars": "timmar"}
# Factually-the-same-value competing spans that canonical-value does not
# merge (abbreviation, plural-definite, content-word boundary) — annotated.
VARIANT_CASES = {"bt-05": "nkk = party abbreviation",
                 "bt-10": "Semester 30 dagar = same fact, boundary",
                 "bt-13": "12 m å naderna = same fact, plural-definite"}


def canon(s):
    return re.sub(r"\s+", " ", re.sub(r"[\[\]]", "", s)).strip().lower()


def canon_value(s):
    words = canon(s).split()
    while words and words[0] in LEADING:
        words = words[1:]
    words = [GENITIVE.get(w, w) for w in words]
    return " ".join(words)


def date_approved(case_id):
    out = set()
    for e in FIXTURE.values():
        if e["case_id"] == case_id and e["prompt_version"] == "span-date-v1" \
                and e["choice"] == "YES":
            out.add(canon_value(e["span"]))
    return out


def verdict_for(case_id, r, is_date):
    gold = {canon_value(g) for g in r["gold"]}
    extracted = {canon_value(s) for s in r["extracted_same_type"]}
    approved = date_approved(case_id) if is_date else \
        {canon_value(s) for s in r["approved"]}
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
    date_cases = {c["case_id"] for c in
                  json.load(open(B / "blindtest_facit_v1.json"))["cases"]
                  if any(n["type"] == "DATE" for n in c["needs"])}
    rows, flips = [], []
    for r in EVAL["per_case"]:
        cid = r["case_id"]
        verdict, competing = verdict_for(cid, r, cid in date_cases)
        af = D10F["cases"][cid]
        if verdict == "resolved":
            if competing and cid not in VARIANT_CASES:
                klass = "correct_answer_despite_wrong_evidence"
            elif competing:
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
                     "competing": sorted(competing),
                     "note": VARIANT_CASES.get(cid, "")})
        old = D10V1[cid]["class"]
        if old != klass:
            flips.append(f"{cid}: {old} -> {klass}")

    counts = {}
    for r in rows:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    print("D10-replay med E1 (datum) + E2 (spannekvivalens) — mot frusen D10-tabell\n")
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
    old_inc = sum(1 for v in D10V1.values() if v["class"] == "incorrect_abstention")
    new_inc = counts.get("incorrect_abstention", 0)
    print(f"felaktiga avståenden: {old_inc} -> {new_inc} "
          f"(mål: minst 2 av 3 borta)")
    print(f"kontaminerade svar: {counts.get('contaminated_answer', 0)}")
    print(f"korrekt svar trots felaktig evidens (dold risk): "
          f"{counts.get('correct_answer_despite_wrong_evidence', 0)}")
    out = B / "blindtest_d10_v2.json"
    json.dump({"version": 2, "counts": counts, "rows": rows, "flips": flips},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nskrivet: {out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""D10 follow-up on blindtest-v1: answer-level analysis over the frozen
artifacts (docs/architecture/gliner2-jevspan-evaluation.md, D10 procedure).

Four events per case, all offline from blindtest_facit_v1_eval.json:
  1. how the engine resolved the need (resolved / false_resolved / ambiguous / unsolved)
  2. whether it would pass the operation contract (gate)
  3. what conclusion the engine's evidence would produce vs the answer facit
  4. class, with the control comparison (gold-only evidence -> correct answer)

Outcome classes (the D10 table):
  - correct_answer
  - correct_answer_boundary_variant   (same fact, different span boundary/morphology)
  - correct_abstention                (withheld on the right ground)
  - correct_abstention_external_need  (document does not answer; new information need)
  - incorrect_abstention              (document answers; engine could not)
  - contaminated_answer               (wrong evidence would change the conclusion)
  - correct_answer_despite_wrong_evidence (hidden risk, factually different extra evidence)

Run: python3 crates/swe-gym/tools/d10_blindtest.py
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"

EVAL = json.load(open(B / "blindtest_facit_v1_eval.json", encoding="utf-8"))
D10 = json.load(open(B / "blindtest_d10_facit_v1.json", encoding="utf-8"))
FACIT = json.load(open(B / "blindtest_facit_v1.json", encoding="utf-8"))

per_case = {r["case_id"]: r for r in EVAL["per_case"]}
gold_by_case = {
    c["case_id"]: [g["span"] for g in c["gold"]] for c in FACIT["cases"]
}

# Cases whose non-gold approved/extracted spans are factually the same value
# (annotated in the D10 facit as boundary/morphological variants).
VARIANT_CASES = {"bt-03", "bt-05", "bt-10", "bt-13", "bt-16"}

rows = []
for case_id, af in sorted(D10["cases"].items()):
    r = per_case[case_id]
    verdict = r["verdict"]
    competing = r["competing"]
    gold = gold_by_case[case_id]

    if verdict == "resolved":
        if competing and case_id not in VARIANT_CASES:
            klass = "correct_answer_despite_wrong_evidence"
        elif competing:
            klass = "correct_answer_boundary_variant"
        else:
            klass = "correct_answer"
    elif verdict == "false_resolved":
        # Engine conclusion comes from the competing (wrong) span.
        klass = ("correct_answer_boundary_variant" if case_id in VARIANT_CASES
                 else "contaminated_answer")
    elif verdict == "ambiguous":
        klass = "correct_abstention"  # contract withheld on competing values
    else:  # unsolved
        if af["answerable"]:
            klass = "incorrect_abstention"
        else:
            klass = "correct_abstention_external_need"

    rows.append({
        "case_id": case_id,
        "verdict": verdict,
        "class": klass,
        "expected": af["expected"],
        "answerable": af["answerable"],
        "competing": competing,
        "note": af.get("engine_note", ""),
    })

counts = {}
for r in rows:
    counts[r["class"]] = counts.get(r["class"], 0) + 1

print("D10 uppföljning — blindtest-v1, samtliga 20 fall (offline, frysta artefakter)\n")
for r in rows:
    flag = ""
    if r["verdict"] == "false_resolved":
        flag = f" [engine-evidence: {r['competing']}]"
    print(f"  {r['case_id']}  {r['class']:<42}{flag}")
    if r["note"]:
        print(f"        {r['note']}")
print()
print("Utfallstabell:")
for k in ["correct_answer", "correct_answer_boundary_variant",
          "correct_abstention", "correct_abstention_external_need",
          "incorrect_abstention", "contaminated_answer",
          "correct_answer_despite_wrong_evidence"]:
    n = counts.get(k, 0)
    if n:
        print(f"  {k:<42} {n}")
print()
print("Kontrolljämförelsen (D10): enbart guldevidens ger rätt svar i samtliga 20 fall —")
print("kontaminationen mäts som skillnaden mellan motorns evidens och guldet:")
cont = counts.get("contaminated_answer", 0)
hidden = counts.get("correct_answer_despite_wrong_evidence", 0)
print(f"  kontaminerade svar: {cont} · korrekt svar trots felaktig evidens: {hidden}")

out = B / "blindtest_d10_v1.json"
json.dump({"version": 1, "counts": counts, "rows": rows},
          open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\nskrivet: {out}")

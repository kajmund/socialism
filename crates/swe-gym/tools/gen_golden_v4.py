#!/usr/bin/env python3
"""The breaking set (docs/SWE_Sweycoins_v2.md 31): golden questions that
try to BREAK the engine — value-type traps, conditional structures,
annex dependencies, missing documents and gated legal interpretation.
Facit is derived deterministically from the documents' actual content;
each case names the typed operation it exercises.

Output: benchmarks/golden_v4.json + golden_v4_verify.txt
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
BENCH = B / "bench_real_v2.json"
OUT = B / "golden_v4.json"
VERIFY = B / "golden_v4_verify.txt"


def main():
    d = json.load(open(BENCH, encoding="utf-8"))
    texts = {}
    for q in d["questions"]:
        texts.update(q.get("texts", {}))

    cases = []
    verify = []

    def add(qid, operation, question, evidence, conclusion, note):
        cases.append({
            "id": f"g4-{qid:02d}",
            "operation": operation,
            "question": question,
            "evidence": sorted(evidence),
            "conclusion": conclusion,
            "note": note,
        })
        verify.append(f"=== g4-{qid:02d} [{operation}] {question}\n    slutsats: {conclusion}\n")
        for c in sorted(evidence):
            verify.append(f"    evidens {c}: {texts[c][:150]!r}")
        verify.append("")

    # 1. Value-type trap: the 12-month non-compete is NOT a notice period.
    add(
        1,
        "EVALUATE_VALUE_TYPE",
        "Hur lång är uppsägningstiden enligt Avtal_81_VD_anstallningsavtal?",
        ["Avtal_81_VD_anstallningsavtal:18", "Avtal_81_VD_anstallningsavtal:25"],
        "6 månader (12 månader avser konkurrensbegränsning, inte uppsägningstid)",
        "fälla: två tidsvärden i samma dokument — operationen måste skilja faktatyper",
    )

    # 2. Conditional structure: the answer depends on the chosen alternative.
    add(
        2,
        "APPLY_CONDITION",
        "Hur länge gäller hyresförhållandet enligt Avtal_18_Hyresavtal_bostad?",
        ["Avtal_18_Hyresavtal_bostad:5", "Avtal_18_Hyresavtal_bostad:6"],
        "beror på valt alternativ: A tills vidare (3 månaders uppsägningstid) eller B bestämd tid",
        "villkor: operationen upptäcker behovet 'vilket alternativ gäller?' och ska avstå om det inte kan lösas",
    )

    # 3. Annex dependency with missing content.
    add(
        3,
        "RESOLVE_ANNEX",
        "Vilka priser gäller enligt Avtal_32_Inkopsavtal?",
        ["Avtal_32_Inkopsavtal:7"],
        "avstå: Bilaga 2 saknas i korpusen",
        "bilagebehov: operationen skapar ett nytt beroende som inte kan lösas — avstå utan att gissa",
    )

    # 4. Missing clause (negative).
    add(
        4,
        "VERIFY_ABSENCE",
        "Innehåller Avtal_15_Bonusavtal en klausul om force majeure?",
        [],
        "nej",
        "saknat faktum: frågan kräver ett nej, inte en gissning",
    )

    # 5. Gated legal interpretation: three inputs, reasoning operation.
    add(
        5,
        "SYNTHESIZE_RISK",
        "Vilken part bär den ekonomiska risken vid förtida uppsägning enligt Avtal_81_VD_anstallningsavtal?",
        [
            "Avtal_81_VD_anstallningsavtal:18",
            "Avtal_81_VD_anstallningsavtal:19",
            "Avtal_81_VD_anstallningsavtal:20",
        ],
        "Bolaget bär ekonomisk risk vid uppsägning (avgångsvederlag om 6 månadslöner), utom vid väsentligt avtalsbrott (omedelbar verkan utan vederlag)",
        "resonemangsoperation: får bara köras när alla tre indata är RESOLVED — grinden får inte kringgås",
    )

    # 6. Exception rule: automatic renewal unless terminated.
    add(
        6,
        "APPLY_EXCEPTION",
        "Förlängs avtalet automatiskt enligt Avtal_20_Arrendeavtal_lagenhetsarrende?",
        ["Avtal_20_Arrendeavtal_lagenhetsarrende:7"],
        "ja, med ett (1) år i taget, OM ingen part säger upp senast sex (6) månader före utgång",
        "undantagsregel: slutsatsen är villkorad — svaret måste bära villkoret",
    )

    payload = {"version": 1, "questions": cases}
    json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    VERIFY.write_text("\n".join(verify), encoding="utf-8")
    print(f"genererade {len(cases)} brytfall (operationskontrakt: "
          + ", ".join(c["operation"] for c in cases) + ")")
    print(f"verifikationslogg: {VERIFY}")
    print("ärligt protokoll: äkta samma-fakta-motsägelser saknas i korpusen — "
          "motsägelsetestet skjuts till rikare dokument.")


if __name__ == "__main__":
    main()

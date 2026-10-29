#!/usr/bin/env python3
"""Level 2 — the counterfactual decision tree (docs/SWE_Sweycoins_v2.md
28): conditional sequences with early stopping over the 104 frozen
states, the four-gap error taxonomy, and the four cost concepts.

Everything is offline: the actions' outcomes are frozen in
action_market/states.txt; the deterministic extraction is recomputed.

Usage: python3 crates/swe-gym/tools/measure_sequences.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_golden_v2 import extract_duration  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"

STATES = B / "action_market" / "states.txt"
GOLDEN = B / "golden_v3.json"
BENCH = B / "bench_real_v2.json"
OUT = B / "golden_v3_sequences.json"

JEV_COST = 1_000  # marginal: one coin per call
EXTRACT_COST = 0  # marginal: local regex over already-fetched text


def main():
    golden = {q["id"]: q for q in json.load(open(GOLDEN, encoding="utf-8"))["questions"]}
    evidence_by_case = {q["id"]: set(q["evidence"]) for q in golden.values()}
    texts = {}
    for q in json.load(open(BENCH, encoding="utf-8"))["questions"]:
        texts.update(q.get("texts", {}))

    states = []
    for line in STATES.read_text(encoding="utf-8").splitlines():
        qid, chunk, baseline, clarified, context = line.split("|")
        states.append({
            "qid": qid,
            "chunk": chunk,
            "baseline": baseline,
            "clarified": clarified,
            "context": context,
            "facit": chunk in evidence_by_case.get(qid, set()),
            "value": extract_duration(texts.get(chunk, "")),
        })

    none_states = [s for s in states if s["baseline"] == "inget"]
    fn = [s for s in none_states if s["facit"]]
    tn = [s for s in none_states if not s["facit"]]
    print(f"beslutsrelevanta tillstånd (baslinje NONE): {len(none_states)} "
          f"(facit-evidens {len(fn)}, äkta negativa {len(tn)})")

    # --- Four-gap taxonomy over the false negatives -------------------
    # retrieval-gap: evidence never fetched — none here (all 13 ARE in
    # the candidate set by construction; the corpus-level cases are the
    # 'ej i pool' ones from earlier runs, recorded separately).
    retrieval_gap = 0
    recognition = [s for s in fn if s["value"] is not None]
    extraction_gap = [s for s in fn if s["value"] is None]
    reasoning_gap = 0  # facts present, conclusion wrong — from the
    # states run: READY cases with all variants wrong (g3-08/11/12).
    print(f"\nfyr-gap-klassificering (falskt negativa, {len(fn)} st):")
    print(f"  retrieval-gap   {retrieval_gap:>3} (evidens aldrig hämtad — här: ingen, kandidaterna innehöll allt)")
    print(f"  recognition-gap {len(recognition):>3} (hämtad, värde extraherbart, baslinjen sade NONE)")
    print(f"  extraction-gap  {len(extraction_gap):>3} (hämtad, men extraktorn hittar inget värde)")
    print(f"  reasoning-gap   {reasoning_gap:>3} (alla fakta på plats, slutsatsen fel — se g3-08/11/12)")
    # Observable signals that separate the gaps (production policy sees
    # only these): value extractable -> recognition-gap candidate;
    # baseline fynd + no value -> extraction-gap; no fynd + no value +
    # chunk not in pool -> retrieval-gap.

    # --- Level 2: conditional sequences with early stopping -----------
    def run_sequence(name, steps):
        """steps: list of (action, cost, verdict_fn, stop_fn)."""
        recovered, fps, spent, stopped_first = 0, 0, 0, 0
        detail = []
        for s in none_states:
            cost = 0
            resolved = False
            first = True
            for action, c, verdict, is_resolved in steps:
                v = verdict(s)
                resolved = is_resolved(v)
                if action != "stop":
                    cost += c
                if resolved:
                    if first:
                        stopped_first += 1
                    break
                first = False
            spent += cost
            if resolved:
                if s["facit"]:
                    recovered += 1
                    detail.append((s["chunk"], cost))
                else:
                    fps += 1
        return recovered, fps, spent, stopped_first, detail

    sequences = {
        "extrahera först, kontext-JEV vid behov": [
            ("extract", EXTRACT_COST, lambda s: s["value"], lambda v: v is not None),
            ("context", JEV_COST, lambda s: s["context"] == "fynd", lambda v: v),
        ],
        "kontext-JEV först, extrahera vid behov": [
            ("context", JEV_COST, lambda s: s["context"] == "fynd", lambda v: v),
            ("extract", EXTRACT_COST, lambda s: s["value"], lambda v: v is not None),
        ],
        "förtydligad JEV först, stoppa annars": [
            ("clarified", JEV_COST, lambda s: s["clarified"] == "fynd", lambda v: v),
        ],
        "stopp utan investering": [
            ("stop", 0, lambda s: False, lambda v: False),
        ],
    }

    print(f"\n{'strategi':<40} {'återfunna':>10} {'falska pos.':>11} {'kostnad':>8} {'1:a-steget':>10}")
    results = {}
    for name, steps in sequences.items():
        rec, fp, spent, first, detail = run_sequence(name, steps)
        results[name] = {
            "recovered": rec,
            "false_positives": fp,
            "marginal_cost": spent,
            "cost_per_recovered": spent / rec if rec else float("inf"),
            "stopped_first_step": first,
        }
        print(f"{name:<40} {rec:>10}/{len(fn)} {fp:>11}/{len(tn)} {spent:>8} {first:>10}")

    # --- Cost concepts (the review's four) ------------------------------
    print("\nkostnadsmodellen (fyra begrepp):")
    print(f"  marginalkostnad: JEV-anrop {JEV_COST} milli, extraktion {EXTRACT_COST} (lokalt, redan hämtad text)")
    print(f"  ackumulerad kostnad: per tillstånd = redan spenderade hämtnings-/bedömningskostnader (sunk)")
    print(f"  allokerad kostnad: ~8 400 per återfunnet = totalsvep över alla 92 NONE-tillstånd / 11 träffar;")
    print(f"     det är ett ALLOKERAT medel, inte marginalkostnaden — validering riktad av signaler")
    print(f"     (extraherbart värde) kostar 1 coin per träff och slösar nästan inget på äkta negativa.")
    print(f"  förväntad kostnad: motorns skattning före beslutet — från de kalibrerade signalerna")
    print(f"     (P(faktum | extraherbart värde) ≈ 0.86 från §27).")
    print(f"  falska positiva redovisas separat: en billig verifierare som felaktigt RESOLVE:ar ett")
    print(f"     REQUIRED-behov kan kosta mer i felaktiga slutsatser än den sparar i coins.")

    json.dump(
        {"sequences": results, "gaps": {
            "retrieval": retrieval_gap, "recognition": len(recognition),
            "extraction": len(extraction_gap), "reasoning": reasoning_gap}},
        open(OUT, "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=2,
    )
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Action-market facit (docs/SWE_Sweycoins_v2.md 27): for every frozen
state, what each action actually would have yielded. Computes action
marginal value, the epistemic/verification uncertainty split, and
calibrates independent relevance signals against the facit.

Usage: python3 crates/swe-gym/tools/measure_market.py
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
OUT = B / "golden_v3_market.json"

JEV_COST = 1_000  # one coin per call; accept/extraction cost nothing extra


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
            "facit_evidence": chunk in evidence_by_case.get(qid, set()),
            "value": extract_duration(texts.get(chunk, "")),
        })

    # The decision-relevant subset: states where the baseline said NONE.
    none_states = [s for s in states if s["baseline"] == "inget"]
    fn_states = [s for s in none_states if s["facit_evidence"]]
    tn_states = [s for s in none_states if not s["facit_evidence"]]

    def action_facit(verdict_of):
        recovered = sum(1 for s in fn_states if verdict_of(s))
        fps = sum(1 for s in tn_states if verdict_of(s))
        cost = JEV_COST * len(none_states)
        return recovered, fps, cost

    actions = {
        "accept NONE": lambda s: s["baseline"] == "fynd",
        "clarified JEV": lambda s: s["clarified"] == "fynd",
        "context JEV": lambda s: s["context"] == "fynd",
        "deterministic extraction": lambda s: s["value"] is not None,
    }

    print(f"frysta tillstånd: {len(states)} (baslinje NONE: {len(none_states)}, "
          f"varav facit-evidens {len(fn_states)}, äkta negativa {len(tn_states)})")
    print(f"\n{'åtgärd':<26} {'återfunna fakta':>15} {'falska positiva':>15} {'kostnad/återfunnet':>18}")
    results = {}
    for name, f in actions.items():
        rec, fp, cost = action_facit(f)
        per = cost / rec if rec else float("inf")
        results[name] = {"recovered": rec, "false_positives": fp, "cost": cost, "cost_per_recovered": per}
        print(f"{name:<26} {rec:>15}/{len(fn_states)} {fp:>15}/{len(tn_states)} {per:>18.0f}")

    # Uncertainty split: verification vs epistemic, on the false-negative
    # states (facit evidence the verifier missed).
    verif = [s for s in fn_states if s["value"] is not None]
    epist = [s for s in fn_states if s["value"] is None]
    print(f"\nosäkerhetssplit (falskt negativa): verifieringsosäkerhet {len(verif)} "
          f"(värdet extraherbart — informationen FINNS), epistemisk {len(epist)} "
          f"(informationen finns inte i chunket)")
    # What would acquisition have added on verification-uncertain states?
    # Nothing — the fact is already there; retrieval on these is pure waste.
    print(f"-> på {len(verif)} tillstånd är ny retrieval/graftraversering kontrafaktiskt värdelös; "
          f"validering återfinner fakta till 1 coin/st")

    # Independent-signal calibration (precision/recall vs facit) — signal
    # agreement is NOT treated as safe; it is calibrated.
    def calibrate(pred):
        tp = sum(1 for s in states if pred(s) and s["facit_evidence"])
        fp = sum(1 for s in states if pred(s) and not s["facit_evidence"])
        fn = sum(1 for s in states if not pred(s) and s["facit_evidence"])
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        return round(prec, 2), round(rec, 2)

    signals = {
        "baseline fynd": lambda s: s["baseline"] == "fynd",
        "clarified fynd": lambda s: s["clarified"] == "fynd",
        "context fynd": lambda s: s["context"] == "fynd",
        "extraherbart värde": lambda s: s["value"] is not None,
        "fynd OCH värde": lambda s: (s["clarified"] == "fynd" and s["value"] is not None),
    }
    print("\nkalibrering av oberoende signaler mot facit (precision / recall):")
    cal = {}
    for name, p in signals.items():
        prec, rec = calibrate(p)
        cal[name] = {"precision": prec, "recall": rec}
        print(f"  {name:<20} {prec:.2f} / {rec:.2f}")

    json.dump(
        {"states": states, "actions": results, "signals": cal,
         "uncertainty": {"verification": len(verif), "epistemic": len(epist)}},
        open(OUT, "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=2,
    )
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()

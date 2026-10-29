#!/usr/bin/env python3
"""Answer contamination (docs/architecture/gliner2-jevspan-evaluation
.md, D10): follow the five survivors through the operation graph with
the four-event chain — (1) is the need wrongly RESOLVED with the
contaminated evidence, (2) does the wrong span pass the operation's
input contract, (3) does the final conclusion change vs the CONTROL
(same operation, gold-only evidence)? Plus the general-class
assessment: contract-expressible vs JEV-semantic responsibility.

Offline from the frozen fixture and the reviewed gold (v3).

Run: python3 crates/swe-gym/tools/analyze_contamination.py
"""

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_gliner_testset import spans_of  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
CHALLENGE = B / "gliner_challenge.json"
FIXTURE = B / "jev_span_fixtures.json"
CANDIDATES_V2 = B / "gliner_candidates_v2.json"
OUT = B / "contamination_analysis.json"

SURVIVORS = ["g5-01", "g5-04", "g5-10", "g5-45", "g5-47"]

PARTY_NAMES = [
    "devbrains ab", "ljusgård design ab", "fastighets ab kvarnberget",
    "jonas ekholm", "petra sandell", "erik lindqvist",
]
FULL_AMOUNT_RE = re.compile(
    r"(?:[a-zåäö]+\s*)+kronor|\d+(?:[.,\s]\d{3})*\s*kronor", re.IGNORECASE,
)


def normalize(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def fixture_key(case_id, span, version):
    digest = hashlib.sha256(
        f"{case_id}\u0000{normalize(span)}\u0000{version}".encode("utf-8")
    ).hexdigest()[:16]
    return digest


def main():
    cases = {c["case_id"]: c for c in json.load(open(CHALLENGE, encoding="utf-8"))["cases"]}
    pop = json.load(open(CANDIDATES_V2, encoding="utf-8"))
    store = {e["key"]: e for e in json.load(open(FIXTURE, encoding="utf-8"))["entries"]}

    def verdict(cid, span):
        key = fixture_key(cid, span, "span-need-contrast-v1")
        return store.get(key, {}).get("choice")

    rows = []
    print(f"{'fall':<7} {'behov':<12} {'(1) felaktigt RESOLVED':<22} {'(2) passerar kontrakt':<20} {'(3) slutsats':<16} {'klass'}")
    for cid in SURVIVORS:
        case = cases[cid]
        need = case["need"]
        gold = [g["span"] for g in case["gold"]]
        approved = [
            info["raw"] for s, info in pop[cid].items()
            if verdict(cid, info["raw"]) == "YES"
        ]
        gold_norm = {normalize(g) for g in gold}
        wrong = [a for a in approved if normalize(a) not in gold_norm]

        # Event 1: the need is resolved (all gold approved) but with
        # contaminated evidence.
        all_gold_ok = all(
            normalize(g) in {normalize(a) for a in approved} for g in gold
        )
        event1 = all_gold_ok and bool(wrong)

        # Event 2: does the wrong span pass the operation's input
        # contract (today's deterministic type checks)?
        def contract_pass(w, need_type):
            if need_type == "NOTICE_PERIOD":
                return bool(re.search(r"månad|år", w, re.IGNORECASE))
            if need_type == "PARTY":
                return True  # any party-ish token passes today
            if need_type == "MONEY":
                return True  # amount-ish tokens pass today
            if need_type == "DATE":
                return bool(re.search(r"\d{4}-\d{2}-\d{2}", w))
            return True
        event2 = all(contract_pass(w, case["need"]) for w in wrong)

        # Event 3 + control: the conclusion from contaminated vs
        # gold-only evidence.
        if case["need"] == "PARTY":
            control = sorted({normalize(g) for g in gold if normalize(g) in PARTY_NAMES})
            contam = sorted({normalize(a) for a in approved if normalize(a) in PARTY_NAMES or normalize(a) == "hyresgästen"})
            conclusion_affected = contam != control
            class_ = "generell regel: en partsroll identifierar inte ensam en juridisk person -> typat kontrakt"
        elif case["need"] == "MONEY":
            control = [g for g in gold if FULL_AMOUNT_RE.search(g)]
            contam = [a for a in approved if FULL_AMOUNT_RE.search(a)]
            if any(normalize(a) == "kronor" for a in wrong):
                class_ = "generell regel: ett belopp ska vara ett fullständigt värde -> typat kontrakt"
                conclusion_affected = True
            else:
                class_ = "semantiskt: vilket belopp som är det operativa -> JEV:s ansvar"
                conclusion_affected = set(contam) != set(control)
        elif case["need"] == "DATE":
            control = sorted({normalize(g) for g in gold})
            contam = sorted({normalize(a) for a in approved})
            conclusion_affected = contam != control
            class_ = "semantiskt: vilket datum som är operativt -> JEV:s ansvar"
        else:  # Ersättning
            control = sorted({normalize(g) for g in gold})
            contam = sorted({normalize(a) for a in approved})
            conclusion_affected = contam != control
            class_ = "semantiskt: generisk term vs konkret åtagande -> JEV:s ansvar"

        rows.append({
            "case_id": cid,
            "need": need,
            "event1_wrongly_resolved": event1,
            "event2_passes_contract": event2,
            "event3_conclusion_affected": conclusion_affected,
            "control_conclusion": control,
            "contaminated_conclusion": contam,
            "class": class_,
        })
        print(f"{cid:<7} {case['need']:<12} {str(event1):<22} {str(event2):<20} "
              f"{str(conclusion_affected):<16} {class_[:58]}")

    contaminated = [r for r in rows if r["event3_conclusion_affected"]]
    print(f"\nsvarskontamination: {len(contaminated)}/5 överlevare kan förvandla "
          f"korrekt underlag till felaktig slutsats")
    print(f"kontrakts-uttryckbara klasser: "
          f"{sum(1 for r in rows if 'kontrakt' in r['class'])}/5")
    print(f"JEV-semantiska klasser: {sum(1 for r in rows if 'JEV' in r['class'])}/5")
    json.dump(rows, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()

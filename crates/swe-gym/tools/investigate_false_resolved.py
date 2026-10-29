#!/usr/bin/env python3
"""The false-RESOLVED investigation (docs/architecture/
gliner2-jevspan-evaluation.md, D8): the 14 needs arm D falsely resolved
— why each was approved, classified into general error classes, and
whether SWE's existing evidence contract could already catch the class.
Also answers the methodological question: can a need count as both
correctly and falsely resolved?

All offline from the frozen JEV fixture.

Run: python3 crates/swe-gym/tools/investigate_false_resolved.py
"""

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
OUT = B / "false_resolved_investigation.json"

NEED_LABELS = {
    "NOTICE_PERIOD": "Uppsägningstid", "SEVERANCE": "Avgångsvederlag",
    "SEVERANCE_VALUE": "Ersättning", "TERMINATION_CONDITION": "Uppsägningsvillkor",
    "RENEWAL": "Förlängning", "PENALTY": "Vite", "LIABILITY_CAP": "Ansvarstak",
    "EXCEPTION": "Undantag", "PARTY": "Avtalspart", "MONEY": "Belopp",
    "DATE": "Datum", "PERIOD": "Tidsperiod",
}

TERM_RE = re.compile(r"upps(ä|a)g|s(ä|a)ger upp|s(ä|a)gs upp|s(ä|a)gas upp|varsel|frånträda|bringa att upphöra", re.IGNORECASE)
RENEW_RE = re.compile(r"förl(ä|a)ng|förny|fortlöper", re.IGNORECASE)
DURATION_RE = re.compile(
    r"\[?\s*(?:([a-zåäö]+)\s*\(?(\d{1,2})\)?|(\d{1,2}))\s*\]?\s*"
    r"(månad(?:er|s)?|dag(?:ar|s)?|veck(?:or|a)?|år)\b",
    re.IGNORECASE,
)


def normalize(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def det_relation(clause):
    text = clause.lower()
    if TERM_RE.search(text):
        return "UPPSÄGNING"
    if RENEW_RE.search(text):
        return "FÖRLÄNGNING"
    if re.search(r"betal|frist", text, re.IGNORECASE):
        return "BETALNING"
    if re.search(r"ansvar|begräns", text, re.IGNORECASE):
        return "ANSVAR"
    if re.search(r"undantag", text, re.IGNORECASE):
        return "UNDANTAG"
    return "ANNAT"


def main():
    cases = json.load(open(CHALLENGE, encoding="utf-8"))["cases"]
    pop = json.load(open(CANDIDATES_V2, encoding="utf-8"))
    fixture = json.load(open(FIXTURE, encoding="utf-8"))
    store = {e["key"]: e for e in fixture["entries"]}

    def d_verdict(cid, span):
        import hashlib
        digest = hashlib.sha256(
            f"{cid}\u0000{normalize(span)}\u0000span-need-contrast-v1".encode("utf-8")
        ).hexdigest()[:16]
        return store.get(digest, {}).get("choice")

    rows = []
    both = 0
    for case in cases:
        cid = case["case_id"]
        need = NEED_LABELS[case["need"]]
        gold = {normalize(g["span"]) for g in case["gold"]}
        det = {normalize(s) for _, s in spans_of(case["clause"])}
        if any(gs not in det and d_verdict(cid, gs) != "YES" for gs in gold):
            continue  # not resolved at all
        # Resolved: which wrong spans were also approved?
        wrong = [
            info["raw"] for s, info in pop[cid].items()
            if s not in gold and d_verdict(cid, info["raw"]) == "YES"
        ]
        if not wrong:
            continue  # correctly resolved
        # Classify each wrong approved span — with the deterministic
        # checks the existing contract machinery CAN make.
        def strip_brackets(x):
            return x.strip("[]").strip()
        gold_stripped = {strip_brackets(g) for g in gold}
        classes = []
        for w in wrong:
            w_norm = normalize(w)
            is_duration = bool(DURATION_RE.search(w))
            rel = det_relation(case["clause"])
            if strip_brackets(w_norm) in gold_stripped:
                classes.append("gräns-artefakt: samma faktum, brackets/whitespace "
                               "skiljer — deterministisk normalisering fångar")
                continue
            if re.search(r"\d{4}-\d{2}-\d{2}", w) and need in ("Uppsägningstid", "Förlängning", "Tidsperiod"):
                classes.append("typkrock: datum godkänt för tidsperiodsbehov — "
                               "deterministisk typkontroll fångar")
                continue
            if w_norm in ("hyresgästen", "vd", "bolaget", "parterna", "uppdragstagaren", "beställaren")                     and need in ("Uppsägningstid", "Förlängning", "Tidsperiod", "Ansvarstak"):
                classes.append("typkrock: part godkänd för icke-partbehov — "
                               "deterministisk typkontroll fångar")
                continue
            if is_duration and rel == "FÖRLÄNGNING" and need in ("Uppsägningstid",):
                classes.append("rätt typ, fel relation: förlängningsperiod godkänd som uppsägningstid")
            elif is_duration and rel == "UPPSÄGNING" and need in ("Förlängning",):
                classes.append("rätt typ, fel relation: uppsägningstid godkänd som förlängning")
            elif is_duration and rel == "BETALNING":
                classes.append("rätt typ, fel relation: betalningsfrist godkänd")
            elif need in ("Uppsägningstid", "Förlängning") and not is_duration:
                classes.append("rätt spann, fel informationsbehov: ej tidsperiod")
            else:
                classes.append("korrekt faktum som inte räcker: " + w_norm[:40])
        rows.append({
            "case_id": cid,
            "need": need,
            "wrong_approved": wrong,
            "classes": classes,
            "deterministic_relation": det_relation(case["clause"]),
            "contract_could_catch": any(
                "deterministisk" in c or "fel relation" in c for c in classes
            ),
        })

    # The methodological question: exclusivity of the two groups.
    # In this counting a need with all gold approved AND wrong spans
    # approved is FALSELY resolved; none are in both groups.
    print(f"falskt lösta behov: {len(rows)}")
    print(f"behov i BÅDA grupperna: {both} — grupperna är ömsesidigt uteslutande")
    print(f"  (semantisk nyans: alla falskt lösta har sina guldfakta godkända — risken är")
    print(f"   att slutsatsen använder ett felaktigt godkänt spann, inte att fakta saknas.)")
    print()
    from collections import Counter
    all_classes = [c for r in rows for c in r["classes"]]
    counts = Counter(all_classes)
    print("felklasser:")
    for cls, n in counts.most_common():
        print(f"  {n:>2}x  {cls}")
    catchable = sum(1 for r in rows if r["contract_could_catch"])
    print(f"\nfall där SWE:s befintliga kontrakt-regler (deterministisk relationskontroll)")
    print(f"redan skulle kunna fånga felet: {catchable}/{len(rows)}")
    json.dump(rows, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()

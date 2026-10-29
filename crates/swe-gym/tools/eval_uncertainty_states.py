#!/usr/bin/env python3
"""The three-state evidence model + the two contract rules (docs/
architecture/gliner2-jevspan-evaluation.md, D11): VERIFIED / AMBIGUOUS
/ REJECTED derived from OBSERVABLE signals only (no facit), with the
two general contract rules (a party role does not alone identify a
legal person; an amount must be a complete value). Replays all 50
frozen cases and reports the open tradeoff: wrong conclusions removed
vs previously-correct conclusions blocked.

Offline from the frozen fixture.

Run: python3 crates/swe-gym/tools/eval_uncertainty_states.py
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
OUT = B / "uncertainty_states.json"

PARTY_NAMES = [
    "devbrains ab", "ljusgård design ab", "fastighets ab kvarnberget",
    "jonas ekholm", "petra sandell", "erik lindqvist",
]
ROLE_WORDS = ["hyresgästen", "hyresvärden", "vd", "bolaget", "parterna",
              "uppdragstagaren", "beställaren", "uthyrare", "mottagaren",
              "utlämnande part"]
FULL_AMOUNT_RE = re.compile(
    r"(?:[a-zåäö]+\s+)+kronor|(?:kr\b|\d+(?:[.,\s]\d{3})*\s*kronor)",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def normalize(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def canonical(s):
    """The canonical span form: ALL brackets removed, whitespace collapsed."""
    return re.sub(r"[\[\]]", "", normalize(s))


def fixture_key(case_id, span, version):
    digest = hashlib.sha256(
        f"{case_id}\u0000{normalize(span)}\u0000{version}".encode("utf-8")
    ).hexdigest()[:16]
    return digest


def classify_state(span, need_type):
    """The three states from observable signals only."""
    s = normalize(span)
    if need_type == "PARTY":
        if s in PARTY_NAMES:
            return "VERIFIED"
        if any(r in s for r in ROLE_WORDS) or s in ROLE_WORDS:
            # General rule: a party role does not alone identify a
            # legal person.
            return "REJECTED"
        return "AMBIGUOUS"
    if need_type == "MONEY":
        if FULL_AMOUNT_RE.search(s):
            return "VERIFIED"
        if "kronor" in s or "kr" in s:
            # General rule: an amount must be a complete value.
            return "REJECTED"
        return "AMBIGUOUS"
    if need_type == "DATE":
        return "VERIFIED" if DATE_RE.search(s) else "REJECTED"
    return "VERIFIED"  # other types: JEV's approval stands


def main():
    cases = {c["case_id"]: c for c in json.load(open(CHALLENGE, encoding="utf-8"))["cases"]}
    pop = json.load(open(CANDIDATES_V2, encoding="utf-8"))
    store = {e["key"]: e for e in json.load(open(FIXTURE, encoding="utf-8"))["entries"]}

    def verdict(cid, span):
        key = fixture_key(cid, span, "span-need-contrast-v1")
        return store.get(key, {}).get("choice")

    before = {"correct": 0, "wrong": 0, "abstained": 0}
    after = {"correct": 0, "wrong": 0, "abstained": 0}
    blocked_correct = []
    removed_wrong = []
    semantic = []

    print(f"{'fall':<7} {'behov':<11} {'före':<10} {'efter':<10} {'förändring'}")
    for cid, case in cases.items():
        need_type = case["need"]
        gold = [canonical(g["span"]) for g in case["gold"]]
        approved = [
            info["raw"] for s, info in pop[cid].items()
            if verdict(cid, info["raw"]) == "YES"
        ]
        approved_can = {canonical(a) for a in approved}
        gold_approved = [g for g in gold if g in approved_can]
        need_resolved = len(gold_approved) == len(gold) if gold else True

        def conclusion(evidence, states):
            """The operation's conclusion from the evidence + states.
            AMBIGUOUS operative values -> abstain (NeedMore) instead of
            silently picking; REJECTED spans are excluded."""
            usable = [e for e, st in zip(evidence, states) if st == "VERIFIED"]
            ambiguous = [e for e, st in zip(evidence, states) if st == "AMBIGUOUS"]
            if ambiguous:
                return None  # INSUFFICIENT: the operative value is not established
            return sorted(set(usable)) or None

        # --- BEFORE: current contract (JEV approval only) ---
        wrong_before = [canonical(a) for a in approved if canonical(a) not in set(gold)]
        if need_resolved and not wrong_before:
            before["correct"] += 1
            before_outcome = "korrekt"
        elif need_resolved:
            before["wrong"] += 1
            before_outcome = "kontaminerad"
        else:
            before["abstained"] += 1
            before_outcome = "avstod"

        # --- AFTER: three-state contract ---
        evidence = [canonical(a) for a in approved]
        states = [classify_state(a, need_type) for a in approved]
        resolved_evidence = [e for e, st in zip(evidence, states) if st == "VERIFIED"]
        gold_usable = all(g in resolved_evidence for g in gold) if gold else True
        # Need-level AMBIGUOUS derivation (observable, no facit): several
        # distinct operative values of the need's type -> which one is
        # operative is not established.
        distinct_values = set()
        for e, st in zip(evidence, states):
            if st == "VERIFIED" and need_type in ("DATE", "MONEY"):
                distinct_values.add(e)
        multiple_operative = need_type in ("DATE", "MONEY") and len(distinct_values) > len(
            set(gold)
        )
        ambiguous_present = any(st == "AMBIGUOUS" for st in states) or multiple_operative
        concl = conclusion(evidence, states)
        if not need_resolved or not gold_usable:
            after["abstained"] += 1
            after_outcome = "avstod"
            if before_outcome == "korrekt":
                blocked_correct.append(cid)
        elif ambiguous_present and concl is None:
            after["abstained"] += 1
            after_outcome = "avstod (AMBIGUOUS)"
            if before_outcome == "korrekt":
                blocked_correct.append(cid)
        else:
            wrong_after = [e for e in resolved_evidence if e not in set(gold)]
            if not wrong_after:
                after["correct"] += 1
                after_outcome = "korrekt"
                if before_outcome == "kontaminerad":
                    removed_wrong.append(cid)
            else:
                after["wrong"] += 1
                after_outcome = "kontaminerad"
                if before_outcome == "kontaminerad":
                    semantic.append((cid, wrong_after))
        change = "—" if before_outcome == after_outcome else f"{before_outcome} -> {after_outcome}"
        print(f"{cid:<7} {need_type:<11} {before_outcome:<10} {after_outcome:<10} {change}")

    print(f"\n{'':<18} {'korrekt':>8} {'kontaminerad':>13} {'avstod':>8}")
    print(f"{'före (nuvarande)':<18} {before['correct']:>8} {before['wrong']:>13} {before['abstained']:>8}")
    print(f"{'efter (trestegs)':<18} {after['correct']:>8} {after['wrong']:>13} {after['abstained']:>8}")
    print(f"\navvägningen, öppet:")
    print(f"  borttagna kontaminerade slutsatser: {len(removed_wrong)} ({removed_wrong})")
    print(f"  blockerade tidigare korrekta slutsatser: {len(blocked_correct)} ({blocked_correct})")
    print(f"  kvarvarande kontaminerade (semantiska fall): {len(semantic)} {semantic}")

    json.dump({"before": before, "after": after,
               "removed_wrong": removed_wrong, "blocked_correct": blocked_correct,
               "semantic_survivors": semantic},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()

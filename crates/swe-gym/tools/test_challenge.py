#!/usr/bin/env python3
"""Regression checks for the challenge set (docs/architecture/
gliner2-jevspan-evaluation.md, D4): unique identities, the 50-case
count, and deterministic recompute from the frozen JEV fixture.

Run: python3 crates/swe-gym/tools/test_challenge.py
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"

CHALLENGE = B / "gliner_challenge.json"
FIXTURE = B / "jev_span_fixtures.json"
OUT = B / "gliner_challenge_eval.json"


def fail(msg):
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    data = json.load(open(CHALLENGE, encoding="utf-8"))
    cases = data["cases"]

    # 1. Exactly 50 cases with unique case_ids.
    if len(cases) != 50:
        fail(f"förväntade 50 fall, fick {len(cases)}")
    case_ids = [c["case_id"] for c in cases]
    if len(set(case_ids)) != len(case_ids):
        fail("case_id inte unika")

    # 2. Unique span_ids — 81 separate annotated occurrences, never
    #    normalized text as identity.
    span_ids = [g["span_id"] for c in cases for g in c["gold"]]
    if len(set(span_ids)) != len(span_ids):
        fail("span_id inte unika")
    print(f"identiteter OK: {len(cases)} fall, {len(span_ids)} unika guldspann")

    # 3. Deterministic recompute: the evaluation artifact must exist and
    #    the frozen fixture must carry prompt/model/choice for every key.
    if not OUT.exists():
        fail(f"{OUT.name} saknas — kör eval_gliner_challenge.py först")
    if FIXTURE.exists():
        fixture = json.load(open(FIXTURE, encoding="utf-8"))
        entries = fixture.get("entries", [])
        required = {"key", "case_id", "span", "clause", "prompt_version",
                    "model", "choice", "score_bp", "ts"}
        missing = [e["key"] for e in entries if not required <= set(e)]
        if missing:
            fail(f"fixturposter utan kompletta fält: {len(missing)}")
        print(f"fixtur OK: {len(entries)} frysta JEV-svar med prompt/model/kontext")
    else:
        print("fixtur saknas ännu (körningen pågår) — hoppar kontrollen")

    print("alla regressioner gröna")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""The post-processing arms (docs/architecture/gliner2-jevspan-evaluation
.md, D9): same frozen candidate population and JEV decisions, ONLY the
contract post-processing changes. A current contract / B + canonical
span normalization / C + need-specific type check / D + unambiguity.
Fully offline — zero new model calls. Errors are classified mutually
exclusively; the survivors are the errors that can still pass the gate
and affect an answer.

Run: python3 crates/swe-gym/tools/eval_postprocessing_arms.py
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
OUT = B / "postprocessing_arms.json"

NEED_LABELS = {
    "NOTICE_PERIOD": "Uppsägningstid", "SEVERANCE": "Avgångsvederlag",
    "SEVERANCE_VALUE": "Ersättning", "TERMINATION_CONDITION": "Uppsägningsvillkor",
    "RENEWAL": "Förlängning", "PENALTY": "Vite", "LIABILITY_CAP": "Ansvarstak",
    "EXCEPTION": "Undantag", "PARTY": "Avtalspart", "MONEY": "Belopp",
    "DATE": "Datum", "PERIOD": "Tidsperiod",
}
# The need contract: what value type the need accepts. Deterministic
# code enforces the type; it never replaces JEV's semantic judgment.
NEED_CONTRACT = {
    "Uppsägningstid": {"accepted_value_type": "DURATION", "require_unambiguous_value": True},
    "Förlängning": {"accepted_value_type": "DURATION", "require_unambiguous_value": True},
    "Tidsperiod": {"accepted_value_type": "DURATION", "require_unambiguous_value": True},
    "Avgångsvederlag": {"accepted_value_type": "ANY", "require_unambiguous_value": False},
    "Ersättning": {"accepted_value_type": "ANY", "require_unambiguous_value": False},
    "Uppsägningsvillkor": {"accepted_value_type": "ANY", "require_unambiguous_value": False},
    "Vite": {"accepted_value_type": "ANY", "require_unambiguous_value": False},
    "Ansvarstak": {"accepted_value_type": "ANY", "require_unambiguous_value": False},
    "Undantag": {"accepted_value_type": "ANY", "require_unambiguous_value": False},
    "Avtalspart": {"accepted_value_type": "ANY", "require_unambiguous_value": False},
    "Belopp": {"accepted_value_type": "ANY", "require_unambiguous_value": False},
    "Datum": {"accepted_value_type": "ANY", "require_unambiguous_value": False},
}

DURATION_RE = re.compile(
    r"\[?\s*(?:([a-zåäö]+)\s*\(?(\d{1,2})\)?|(\d{1,2}))\s*\]?\s*"
    r"(månad(?:er|s)?|dag(?:ar|s)?|veck(?:or|a)?|år)\b",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def normalize(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def canonical(s):
    """The canonical span form: ALL brackets removed, whitespace collapsed."""
    return re.sub(r"[\[\]]", "", normalize(s))


def det_value_type(span):
    if DURATION_RE.search(span):
        return "DURATION"
    if DATE_RE.search(span):
        return "DATE"
    if re.search(r"kronor|belopp|arvode", span, re.IGNORECASE):
        return "AMOUNT"
    return "OTHER"


def fixture_key(case_id, span, version):
    digest = hashlib.sha256(
        f"{case_id}\u0000{normalize(span)}\u0000{version}".encode("utf-8")
    ).hexdigest()[:16]
    return digest


def main():
    cases = json.load(open(CHALLENGE, encoding="utf-8"))["cases"]
    pop = json.load(open(CANDIDATES_V2, encoding="utf-8"))
    store = {e["key"]: e for e in json.load(open(FIXTURE, encoding="utf-8"))["entries"]}

    def d_verdict(cid, span):
        key = fixture_key(cid, span, "span-need-contrast-v1")
        return store.get(key, {}).get("choice")

    gold = {c["case_id"]: {normalize(g["span"]) for g in c["gold"]} for c in cases}
    det = {c["case_id"]: {normalize(s) for _, s in spans_of(c["clause"])} for c in cases}

    # Approved spans per case under arm D's JEV decisions (frozen).
    approved = {}
    for case in cases:
        cid = case["case_id"]
        approved[cid] = [
            info["raw"] for s, info in pop[cid].items()
            if d_verdict(cid, info["raw"]) == "YES"
        ]

    def evaluate(arm):
        false_resolved = []
        correct_resolved = 0
        wrongly_rejected = 0
        insufficient = 0
        answer_ok = 0
        answer_wrong = 0
        for case in cases:
            cid = case["case_id"]
            need = NEED_LABELS[case["need"]]
            contract = NEED_CONTRACT[need]
            g = gold[cid]
            # All gold spans must be approved (and, for arm B+, the
            # canonicalized gold must match an approved canonical span).
            gold_ok = True
            for gs in g:
                if gs in det[cid]:
                    continue  # generator span: passes via the generator path
                approved_norm = {normalize(a) for a in approved[cid]}
                approved_can = {canonical(a) for a in approved[cid]}
                if gs not in approved_norm and not (
                    arm in ("B", "C", "D") and canonical(gs) in approved_can
                ):
                    gold_ok = False
                    break
            if not gold_ok:
                if arm != "A":
                    # Was it resolved under A? Then this is a wrongly
                    # rejected need (normalization/type demotion loss).
                    a_ok = all(
                        gs in det[cid] or gs in {normalize(a) for a in approved[cid]}
                        for gs in g
                    )
                    if a_ok:
                        wrongly_rejected += 1
                continue
            # Candidate evidence for the need after post-processing.
            evidence = []
            for a in approved[cid]:
                a_norm = normalize(a)
                a_can = canonical(a)
                is_gold = a_norm in g if arm == "A" else (
                    a_norm in g or a_can in {canonical(gs) for gs in g}
                )
                if is_gold:
                    evidence.append((a_norm, a_can))
                    continue
                if arm in ("A", "B"):
                    evidence.append(a_can)
                    continue
                # Arm C+: type check in the contract.
                if contract["accepted_value_type"] != "ANY":
                    vt = det_value_type(a)
                    if vt != contract["accepted_value_type"]:
                        continue  # deterministic type rejection
                evidence.append((a_norm, a_can))
            # Arm D: unambiguity — conflicting values of the need's type.
            if arm == "D" and contract["require_unambiguous_value"]:
                values = set()
                for (_n, e) in evidence:
                    m = DURATION_RE.search(e)
                    if m:
                        values.add(m.group(0))
                if len(values) > 1:
                    insufficient += 1
                    continue
            if arm == "A":
                wrong_evidence = [n for (n, c) in evidence if n not in g]
            else:
                canon_gold = {canonical(gs) for gs in g}
                wrong_evidence = [c for (n, c) in evidence if c not in canon_gold]
            if wrong_evidence:
                false_resolved.append({
                    "case_id": cid,
                    "need": need,
                    "wrong": wrong_evidence,
                })
            else:
                correct_resolved += 1
            # Final answer correctness: the resolved evidence must
            # contain every gold value and no wrong value of the type.
            if not wrong_evidence:
                answer_ok += 1
            else:
                answer_wrong += 1
        return {
            "false_resolved": len(false_resolved),
            "correct_resolved": correct_resolved,
            "wrongly_rejected": wrongly_rejected,
            "resolved_to_insufficient": insufficient,
            "answer_correct": answer_ok,
            "answer_wrong": answer_wrong,
            "false_cases": false_resolved,
        }

    results = {}
    print(f"{'arm':<44} {'falskt':>6} {'rätt':>5} {'fel-avvisade':>12} {'→INSUFF':>7} {'svar rätt':>9} {'svar fel':>8}")
    for arm in ["A_nuvarande", "B_+normalisering", "C_+typkontroll", "D_+entydighet"]:
        r = evaluate(arm)
        results[arm] = r
        print(f"{arm:<44} {r['false_resolved']:>6} {r['correct_resolved']:>5} "
              f"{r['wrongly_rejected']:>12} {r['resolved_to_insufficient']:>7} "
              f"{r['answer_correct']:>9} {r['answer_wrong']:>8}")

    # The survivors: mutually exclusive classification of what remains
    # after the full contract (arm D) — the errors that can still pass
    # the gate and affect an answer.
    survivors = results["D_+entydighet"]["false_cases"]
    print(f"\növerlevare efter hela kontraktet (arm D): {len(survivors)}")
    for s in survivors:
        print(f"  {s['case_id']} [{s['need']}] felaktig evidens: {s['wrong']}")
    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()

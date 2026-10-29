#!/usr/bin/env python3
"""The selective verification rule (docs/SWE_Sweycoins_v2.md 29):
extraction first, RESOLVED only when the value is CLEAR — right
document, termination clause context, unambiguous value — context-JEV
otherwise. Evaluated against the four measured strategies, on the full
state set AND a held-out half the rule was not constructed on. Adds the
False Resolution Rate (needs) and answer correctness (final answer).

Usage: python3 crates/swe-gym/tools/measure_selective.py
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_golden_v2 import extract_duration, DURATION_RE, WORD_NUMS  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"

STATES = B / "action_market" / "states.txt"
GOLDEN = B / "golden_v3.json"
BENCH = B / "bench_real_v2.json"
OUT = B / "golden_v3_selective.json"

JEV_COST = 1_000
EXTRACT_COST = 0  # nominal zero at this scale; epsilon scenario below
EPS = 1  # milli per extraction, the CPU/latency scenario

TERM_RE = re.compile(
    r"upps(ä|a)g|s(ä|a)ger upp|s(ä|a)gs upp|s(ä|a)gas upp|avtalstid",
    re.IGNORECASE,
)


def doc_names(question):
    return set(re.findall(r"Avtal_\d+_[A-Za-zåäöÅÄÖ_]+", question))


def months_local(d):
    n, unit = d.split(" ", 1)
    n = int(n)
    return n * {"år": 12, "månad": 1, "månader": 1, "vecka": 0.25, "veckor": 0.25, "dag": 1 / 30, "dagar": 1 / 30}.get(unit, 0)


def all_durations(text):
    out = []
    for m in DURATION_RE.finditer(text):
        word, digits, plain = m.group(1), m.group(2), m.group(3)
        if word and word.lower() in WORD_NUMS:
            n = WORD_NUMS[word.lower()]
        elif digits:
            n = int(digits)
        elif plain:
            n = int(plain)
        else:
            continue
        out.append(f"{n} {m.group(4).lower()}")
    return out


def main():
    golden = {q["id"]: q for q in json.load(open(GOLDEN, encoding="utf-8"))["questions"]}
    evidence_by_case = {q["id"]: set(q["evidence"]) for q in golden.values()}
    compared_docs = {q["id"]: doc_names(q["question"]) for q in golden.values()}
    texts = {}
    for q in json.load(open(BENCH, encoding="utf-8"))["questions"]:
        texts.update(q.get("texts", {}))

    states = []
    for line in STATES.read_text(encoding="utf-8").splitlines():
        qid, chunk, baseline, clarified, context = line.split("|")
        states.append({
            "qid": qid,
            "chunk": chunk,
            "context_jv": context,
            "facit": chunk in evidence_by_case.get(qid, set()),
        })
    # Filter to the decision-relevant set (baseline NONE).
    baseline_by_qid = {}
    for line in STATES.read_text(encoding="utf-8").splitlines():
        qid, chunk, base, clar, ctx = line.split("|")
        baseline_by_qid[(qid, chunk)] = base
    none_states = [s for s in states if baseline_by_qid[(s["qid"], s["chunk"])] == "inget"]

    def selective_rule(s):
        """Clear value -> RESOLVED; uncertain -> context-JEV; else no.
        Defined SEMANTICALLY (domain knowledge), not tuned on the data:
        right document + termination clause context + unambiguous value."""
        text = texts.get(s["chunk"], "")
        dur = extract_duration(text)
        if dur is None:
            return "unresolved", 0
        docs = compared_docs[s["qid"]]
        doc_ok = s["chunk"].split(":")[0] in docs
        context_ok = bool(TERM_RE.search(text))
        unambiguous = len(set(all_durations(text))) <= 1
        if doc_ok and context_ok and unambiguous:
            return "resolved", 0  # deterministic, zero JEV calls
        # Uncertain value — ambiguity, conflict or weak match: pay one
        # context-JEV call before any RESOLVED.
        if not (doc_ok and context_ok and unambiguous):
            return "resolved" if s["context_jv"] == "fynd" else "unresolved", JEV_COST
        return "unresolved", 0

    def evaluate(subset):
        rec, fp, cost = 0, 0, 0
        for s in subset:
            verdict, c = selective_rule(s)
            cost += c
            if verdict == "resolved":
                if s["facit"]:
                    rec += 1
                else:
                    fp += 1
        return rec, fp, cost

    fn_total = [s for s in none_states if s["facit"]]
    tn_total = [s for s in none_states if not s["facit"]]

    # Held-out split: states from g3-07..g3-12 (the rule was designed
    # semantically; this half still demonstrates no overfitting).
    held_out = [s for s in none_states if s["qid"] >= "g3-07"]
    construct = [s for s in none_states if s["qid"] < "g3-07"]

    for label, subset in [("alla 92", none_states), ("konstruktionshalvan", construct), ("hållen halva", held_out)]:
        rec, fp, cost = evaluate(subset)
        n_fn = len([s for s in subset if s["facit"]])
        n_tn = len([s for s in subset if not s["facit"]])
        print(f"selektiv regel på {label:<22}: återfunna {rec:>2}/{n_fn}, "
              f"falska positiva {fp}/{n_tn}, JEV-kostnad {cost}")

    rec, fp, cost = evaluate(none_states)
    print("\njmf. tidigare strategier: extrahera-först 11/13 FP 5 kostnad 78 000; "
          "förtydligad-först 11/13 FP 3 kostnad 92 000")
    print(f"selektiv regel:               {rec}/13 FP {fp} kostnad {cost} "
          f"(+ {EPS * len(none_states)} milli om extraktion kostar 1 milli/chunk)")

    # --- FRR (needs) and answer correctness ---------------------------
    print("\nbehovs- och svarsnivå:")
    for qid, q in golden.items():
        case_states = [s for s in none_states if s["qid"] == qid]
        if not case_states:
            continue
        resolved_docs = {}
        for s in case_states:
            verdict, _c = selective_rule(s)
            if verdict == "resolved":
                text = texts.get(s["chunk"], "")
                d = extract_duration(text)
                if d:
                    resolved_docs.setdefault(s["chunk"].split(":")[0], set()).add(d)
        # A doc is wrongly RESOLVED if it is not among the compared docs'
        # facit evidence (its value would enter the comparison).
        facit_docs = {c.split(":")[0] for c in q["evidence"]}
        wrong_resolved = {d for d in resolved_docs if d not in facit_docs}
        # Deterministic answer from the resolved set.
        answer = None
        values = {d: sorted(vs)[0] for d, vs in resolved_docs.items() if len(vs) == 1}
        if "längst uppsägningstid" in q["question"] and values:
            answer = max(values, key=lambda d: months_local(values[d]))
        correct = answer == q["conclusion"] if answer else False
        frr = len(wrong_resolved) / len(resolved_docs) if resolved_docs else 0.0
        print(f"  {qid}: RESOLVED-dokument {len(resolved_docs)} (felaktiga {len(wrong_resolved)}, "
              f"FRR {frr:.2f}), deterministiskt svar {answer} (facit {q['conclusion']}) -> {'rätt' if correct else 'fel/avstår'}")

    json.dump(
        {"rule": "semantic: doc match + termination context + unambiguous value",
         "full": {"recovered": rec, "false_positives": fp, "cost": cost},
         "extraction_epsilon": EPS},
        open(OUT, "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=2,
    )
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()

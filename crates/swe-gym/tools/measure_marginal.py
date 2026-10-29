#!/usr/bin/env python3
"""Offline marginal-value analysis of the Research Gym measurement
(docs/SWE_Sweycoins_v2.md 19): per capability and combination, measure
evidence coverage, answer correctness and cost from the frozen fixtures,
ranks and golden facit. A capability without marginal value is reported
as such — never compensated.

Usage: python3 crates/swe-gym/tools/measure_marginal.py
Output: crates/swe-gym/benchmarks/golden_v2_measurement.json
"""

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"

GOLDEN = B / "golden_v2.json"
RANKS = B / "golden_v2_ranks.json"
CAND = B / "golden_v2_candidates.json"
BENCH = B / "bench_real_v2.json"
FIX = B / "golden_v2_fixtures"
OUT = B / "golden_v2_measurement.json"

WORD_NUMS = {
    "ett": 1, "en": 1, "två": 2, "tre": 3, "fyra": 4, "fem": 5, "sex": 6,
    "sju": 7, "åtta": 8, "nio": 9, "tio": 10, "elva": 11, "tolv": 12,
}
DURATION_RE = re.compile(
    r"\[?\s*(?:([a-zåäö]+)\s*\(?(\d{1,2})\)?|(\d{1,2}))\s*\]?\s*"
    r"(månad(?:er|s)?|dag(?:ar|s)?|veck(?:or|a)?|år)\b",
    re.IGNORECASE,
)


def extract_duration(text):
    m = DURATION_RE.search(text)
    if not m:
        return None
    word, digits, plain = m.group(1), m.group(2), m.group(3)
    if word and word.lower() in WORD_NUMS:
        n = WORD_NUMS[word.lower()]
    elif digits:
        n = int(digits)
    elif plain:
        n = int(plain)
    else:
        return None
    return f"{n} {m.group(4).lower()}"


def months(d):
    n, unit = d.split(" ", 1)
    n = int(n)
    return n * {"år": 12, "månad": 1, "månader": 1, "vecka": 0.25, "veckor": 0.25, "dag": 1 / 30, "dagar": 1 / 30}.get(unit, 0)


def load_hits(qid, provider):
    path = FIX / f"{qid}-{provider}.json"
    if not path.exists():
        return {}
    data = json.load(open(path, encoding="utf-8"))
    return {
        e["chunk_id"]: e["choice"]
        for e in data.get("entries", [])
    }


def hits_from(answers):
    """Chunks where the capability answered fynd with high confidence."""
    return {
        c
        for c, choice in answers.items()
        if choice == "fynd"
    }


def assemble(question, found_chunks, texts):
    """Deterministic conclusion from the found evidence; None = no answer."""
    category = question["category"]
    if category == "evidenssökning":
        return "ja" if found_chunks else "nej"
    if category == "korsdokument":
        docs = sorted({c.split(":")[0] for c in found_chunks})
        return ", ".join(docs) if docs else "nej"
    # resonemang/syntes: durations from found chunk texts
    durations = []
    for c in found_chunks:
        d = extract_duration(texts.get(c, ""))
        if d:
            durations.append((c, d))
    if not durations:
        return None
    if "längst uppsägningstid" in question["question"]:
        best = max(durations, key=lambda cd: months(cd[1]))
        return best[0].split(":")[0]
    return durations[0][1]


def evaluate(question, found_chunks, texts):
    evidence = set(question["evidence"])
    coverage = len(found_chunks & evidence) / len(evidence) if evidence else 1.0
    answer = assemble(question, found_chunks, texts)
    correct = answer is not None and answer == question["conclusion"]
    return coverage, answer, correct


def main():
    golden = json.load(open(GOLDEN, encoding="utf-8"))["questions"]
    golden_by_id = {q["id"]: q["category"] for q in golden}
    ranks = json.load(open(RANKS, encoding="utf-8"))["ranks"]
    texts = {}
    for q in json.load(open(BENCH, encoding="utf-8"))["questions"]:
        texts.update(q.get("texts", {}))

    jev_cost = 1_000   # 1 coin per call
    llm_cost = 10_000  # 10 coins per call
    plans = {
        "jev-only": lambda qid: set(load_hits(qid, "jev")),
        "llm-only": lambda qid: set(load_hits(qid, "llm")),
        "retrieval+jev": lambda qid: set(load_hits(qid, "jev")),
        "retrieval+jev+llm": lambda qid: set(load_hits(qid, "jev")) | set(load_hits(qid, "llm")),
    }

    invalid_log = {}
    invalid_path = FIX / "invalid_answers.txt"
    if invalid_path.exists():
        for line in invalid_path.read_text(encoding="utf-8").splitlines():
            parts = line.split(" ")
            if len(parts) >= 2:
                key = parts[1]  # provider name (JEV/LLM)
                invalid_log[key] = invalid_log.get(key, 0) + 1

    results = {}
    for plan, choose in plans.items():
        rows = []
        total_jev = total_llm = 0
        for q in golden:
            qid = q["id"]
            jev_hits = hits_from(load_hits(qid, "jev"))
            llm_hits = hits_from(load_hits(qid, "llm"))
            if plan == "jev-only":
                found = jev_hits
            elif plan == "llm-only":
                found = llm_hits
            elif plan == "retrieval+jev":
                order = ranks[qid]
                found = jev_hits  # verified in rank order; all verified here
            else:
                found = jev_hits | llm_hits
            # retrieval+*: respect the rank budget (top 12 candidates)
            if plan.startswith("retrieval+"):
                order = ranks[qid][:12]
                found = {c for c in found if c in order}
            coverage, answer, correct = evaluate(q, found, texts)
            n_jev = len(load_hits(qid, "jev"))
            n_llm = len(load_hits(qid, "llm"))
            total_jev += n_jev
            total_llm += n_llm
            rows.append(
                {
                    "id": qid,
                    "coverage": round(coverage, 3),
                    "answer": answer,
                    "correct": correct,
                }
            )
        results[plan] = {
            "coverage_mean": round(sum(r["coverage"] for r in rows) / len(rows), 3),
            "correctness": round(sum(r["correct"] for r in rows) / len(rows), 3),
            "jev_calls": total_jev,
            "llm_calls": total_llm,
            "cost_milli": total_jev * jev_cost + total_llm * llm_cost,
            "rows": rows,
        }
    results["_invalid_answers"] = invalid_log

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"{'plan':<22} {'täckning':>9} {'korrekthet':>11} {'JEV-anrop':>9} {'LLM-anrop':>9} {'kostnad':>9}")
    for plan, r in results.items():
        if plan.startswith("_"):
            continue
        print(
            f"{plan:<22} {r['coverage_mean']:>9.2f} {r['correctness']:>11.2f} "
            f"{r['jev_calls']:>9} {r['llm_calls']:>9} {r['cost_milli']:>9}"
        )
    print("ogiltiga svar:", results.get("_invalid_answers", {}))
    # per-category correctness
    print("\nper kategori (retrieval+jev+llm):")
    for cat in ("evidenssökning", "korsdokument", "resonemang/syntes"):
        rows = [r for r in results["retrieval+jev+llm"]["rows"] if golden_by_id[r["id"]] == cat]
        cov = sum(r["coverage"] for r in rows) / len(rows)
        cor = sum(r["correct"] for r in rows) / len(rows)
        print(f"  {cat:<22} täckning {cov:.2f}  korrekthet {cor:.2f}  ({len(rows)} frågor)")
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()

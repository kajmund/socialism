#!/usr/bin/env python3
"""Offline chain comparison (docs/SWE_Sweycoins_v2.md 21): four execution
chains per question at the same Sweycoin budget, from the frozen fixtures
and the captured synthesis answers. Measures cost, coverage and
correctness per chain, plus the facit-reasoning review.

Usage: python3 crates/swe-gym/tools/measure_chains.py
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_golden_v2 import extract_duration  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"

GOLDEN = B / "golden_v2.json"
FIX = B / "golden_v2_fixtures"
SYNTH = B / "chain_synthesis" / "answers.txt"
OUT = B / "golden_v2_chains.json"

QUESTIONS = ["g2-15", "g2-17", "g2-29", "g2-20", "g2-23"]

DOC_RE = re.compile(r"Avtal_\d+_[A-Za-zåäöÅÄÖ]+")

JEV_COST = 1_000
LLM_COST = 10_000


def months(d):
    n, unit = d.split(" ", 1)
    n = int(n)
    return n * {"år": 12, "månad": 1, "månader": 1, "vecka": 0.25, "veckor": 0.25, "dag": 1 / 30, "dagar": 1 / 30}.get(unit, 0)


def load_hits(qid, provider):
    data = json.load(open(FIX / f"{qid}-{provider}.json", encoding="utf-8"))
    return {e["chunk_id"] for e in data["entries"] if e["choice"] == "fynd"}


def assembler(question, found, texts):
    """Deterministic conclusion from found evidence (chains A and B)."""
    if "längst uppsägningstid" in question["question"]:
        durations = []
        for c in found:
            d = extract_duration(texts.get(c, ""))
            if d:
                durations.append((c, d))
        if not durations:
            return None
        return max(durations, key=lambda cd: months(cd[1]))[0].split(":")[0]
    docs = sorted({c.split(":")[0] for c in found})
    return docs


def recover_content(answer):
    """The synthesis capture stored invalid-format answers as
    'FEL: invalid LLM answer ... (content: ...)'. The actual content is
    recovered; the format refusal itself is a counted capability fact."""
    marker = "(content: "
    if answer.startswith("FEL:") and marker in answer:
        return answer.split(marker, 1)[1].rsplit('")', 1)[0]
    return answer


def normalize_answer(answer, question):
    answer = recover_content(answer)
    docs = sorted(set(DOC_RE.findall(answer)))
    if "längst uppsägningstid" in question["question"]:
        return docs[0] if docs else None
    if question["category"] == "korsdokument":
        return docs
    d = extract_duration(answer)
    return d


def correct(facit, normalized, question):
    if normalized is None:
        return False
    if question["category"] == "korsdokument":
        return set(normalized) == set(re.split(r",\s*", facit))
    return normalized == facit or facit in normalized


def main():
    golden = {q["id"]: q for q in json.load(open(GOLDEN, encoding="utf-8"))["questions"]}
    texts = {}
    for q in json.load(open(B / "bench_real_v2.json", encoding="utf-8"))["questions"]:
        texts.update(q.get("texts", {}))
    synthesis = {}
    block = {}
    key = None
    for line in SYNTH.read_text(encoding="utf-8").splitlines():
        if line.startswith("=== "):
            key = line[4:].strip()
            block = {}
        elif key and line.startswith(("QUESTION:", "CHAIN_C:", "CHAIN_D_NEEDS:", "CHAIN_D:")):
            k, _, v = line.partition(":")
            block[k] = v.strip()
        if key and "CHAIN_D" in block:
            synthesis[key] = block

    results = {}
    for qid in QUESTIONS:
        q = golden[qid]
        jev = load_hits(qid, "jev")
        llm = load_hits(qid, "llm")
        syn = synthesis.get(qid, {})
        n_jev = len(json.load(open(FIX / f"{qid}-jev.json", encoding="utf-8"))["entries"])
        n_llm = len(json.load(open(FIX / f"{qid}-llm.json", encoding="utf-8"))["entries"])

        a_norm = assembler(q, jev, texts)
        b_norm = assembler(q, llm, texts)
        c_norm = normalize_answer(syn.get("CHAIN_C", ""), q)
        needs = [
            k.strip().lower()
            for k in recover_content(syn.get("CHAIN_D_NEEDS", "")).split(",")
            if k.strip()
        ]
        filtered = {c for c in jev if any(k and k in texts.get(c, "").lower() for k in needs)}
        d_norm = normalize_answer(syn.get("CHAIN_D", ""), q)

        def coverage(found):
            return len(found & set(q["evidence"])) / max(1, len(q["evidence"]))

        results[qid] = {
            "question": q["question"],
            "category": q["category"],
            "facit": q["conclusion"],
            "facit_requires_aggregation": len(q["evidence"]) > 1 or q["category"] == "korsdokument",
            "chains": {
                "jev->assembler": {
                    "cost": n_jev * JEV_COST,
                    "coverage": round(coverage(jev), 3),
                    "conclusion": a_norm,
                    "correct": correct(q["conclusion"], a_norm, q),
                },
                "llm->assembler": {
                    "cost": n_llm * LLM_COST,
                    "coverage": round(coverage(llm), 3),
                    "conclusion": b_norm,
                    "correct": correct(q["conclusion"], b_norm, q),
                },
                "jev->llm": {
                    "cost": n_jev * JEV_COST + LLM_COST,
                    "coverage": round(coverage(jev), 3),
                    "conclusion": c_norm,
                    "correct": correct(q["conclusion"], c_norm, q),
                },
                "llm->jev->llm": {
                    "cost": 2 * LLM_COST + len(filtered) * JEV_COST,
                    "coverage": round(coverage(filtered), 3),
                    "conclusion": d_norm,
                    "correct": correct(q["conclusion"], d_norm, q),
                },
            },
        }

    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"{'kedja':<18} {'kostnad(medel)':>14} {'täckning':>9} {'korrekthet':>11}")
    for chain in ["jev->assembler", "llm->assembler", "jev->llm", "llm->jev->llm"]:
        costs = [r["chains"][chain]["cost"] for r in results.values()]
        covs = [r["chains"][chain]["coverage"] for r in results.values()]
        cors = [r["chains"][chain]["correct"] for r in results.values()]
        print(
            f"{chain:<18} {sum(costs)/len(costs):>14.0f} {sum(covs)/len(covs):>9.2f} "
            f"{sum(cors)/len(cors):>11.2f}"
        )
    print("\nfacit-granskning (kräver aggregering, ej enkelchunk):")
    for qid, r in results.items():
        print(
            f"  {qid}: {'ja' if r['facit_requires_aggregation'] else 'nej'} "
            f"(evidens-chunks: {len(golden[qid]['evidence'])})"
        )
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()

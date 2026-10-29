#!/usr/bin/env python3
"""Three-state experiment analysis (docs/SWE_Sweycoins_v2.md 25):
A — SWE stops guessing when evidence is insufficient (gate vs baseline).
B — SWE investigates until all REQUIRED needs are resolved or aborts.
C — SWE can draw the right conclusion from complete evidence (the
milestone's remaining criterion), across four synthesis variants:
baseline (previous iterative), gate+LLM, gate+matrix+LLM, and the
deterministic assembler (no LLM at all — the Sweycoin win).

Usage: python3 crates/swe-gym/tools/measure_states.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from measure_chains import correct, normalize_answer, recover_content  # noqa: E402
from gen_golden_v2 import extract_duration  # noqa: E402


def months(d):
    n, unit = d.split(" ", 1)
    n = int(n)
    return n * {"år": 12, "månad": 1, "månader": 1, "vecka": 0.25, "veckor": 0.25, "dag": 1 / 30, "dagar": 1 / 30}.get(unit, 0)

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"

GOLDEN = B / "golden_v3.json"
STATES = B / "states_capture"
MILESTONE = B / "milestone_capture" / "answers.txt"
OUT = B / "golden_v3_states.json"


def deterministic_conclusion(question, hits, texts):
    """The deterministic assembler: extract durations per document and
    compare — no LLM. Returns (answer, contradictions)."""
    if "längst uppsägningstid" in question["question"]:
        per_doc = {}
        contradictions = []
        for c in hits:
            d = extract_duration(texts.get(c, ""))
            if not d:
                continue
            doc = c.split(":")[0]
            if doc in per_doc and per_doc[doc] != d:
                contradictions.append((doc, per_doc[doc], d))
            per_doc[doc] = d
        if not per_doc:
            return None, contradictions
        best = max(per_doc, key=lambda doc: months(per_doc[doc]))
        return best, contradictions
    return None, []


def main():
    golden = {q["id"]: q for q in json.load(open(GOLDEN, encoding="utf-8"))["questions"]}
    texts = {}
    for q in json.load(open(B / "bench_real_v2.json", encoding="utf-8"))["questions"]:
        texts.update(q.get("texts", {}))

    blocks = {}
    block = {}
    key = None
    for line in (STATES / "answers.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("=== "):
            key = line[4:].strip()
            block = {}
        elif key and line.startswith(("STATE:", "NEEDS:", "HITS:", "GATE_SYNTH:", "MATRIX_CONCLUSION:")):
            k, _, v = line.partition(":")
            block[k] = v.strip()
        if key and "MATRIX_CONCLUSION" in block:
            blocks[key] = block

    # Baseline answers from the previous iterative chain (no gate).
    baseline = {}
    bblock = {}
    bkey = None
    for line in MILESTONE.read_text(encoding="utf-8").splitlines():
        if line.startswith("=== "):
            bkey = line[4:].strip()
            bblock = {}
        elif bkey and line.startswith(("STATIC:", "ITERATIVE:")):
            k, _, v = line.partition(":")
            bblock[k] = v.strip()
        if bkey and "ITERATIVE" in bblock:
            baseline[bkey] = bblock

    rows = {}
    a_count = 0
    b_ready = 0
    c_variants = {"gate_llm": 0, "matrix_llm": 0, "deterministic": 0}
    milestone = []
    for qid, q in golden.items():
        block = blocks.get(qid, {})
        if not block:
            continue
        state = block.get("STATE", "?")
        hits = [h for h in block.get("HITS", "").split(";") if h]

        needs = []
        for nline in block.get("NEEDS", "").split("||"):
            nline = nline.strip()
            if not nline:
                continue
            parts = nline.split("|")
            if len(parts) >= 5:
                needs.append({
                    "need": parts[0],
                    "document": parts[1],
                    "importance": parts[2],
                    "status": parts[3],
                    "evidence": [e for e in parts[4].split(";") if e],
                })

        static_correct = False
        base_iter_correct = False
        if qid in baseline:
            b = baseline[qid]
            static_norm = normalize_answer(recover_content(b.get("STATIC", "")), q)
            static_correct = correct(q["conclusion"], static_norm, q)
            iter_norm = normalize_answer(recover_content(b.get("ITERATIVE", "")), q)
            base_iter_correct = correct(q["conclusion"], iter_norm, q)

        gate_norm = normalize_answer(recover_content(block.get("GATE_SYNTH", "-")), q)
        matrix_norm = normalize_answer(recover_content(block.get("MATRIX_CONCLUSION", "-")), q)
        gate_correct = correct(q["conclusion"], gate_norm, q)
        matrix_correct = correct(q["conclusion"], matrix_norm, q)
        det_answer, contradictions = deterministic_conclusion(q, hits, texts)
        det_correct = det_answer is not None and det_answer == q["conclusion"]

        # A: the gate prevented a guess the ungated chain made.
        guessed_before = base_iter_correct or (qid in baseline and normalize_answer(recover_content(baseline[qid].get("ITERATIVE", "")), q) is not None)
        gate_blocked = state == "INSUFFICIENT_EVIDENCE"
        if gate_blocked and guessed_before:
            a_count += 1
        if state == "READY_TO_SYNTHESIZE":
            b_ready += 1
        c_variants["gate_llm"] += gate_correct
        c_variants["matrix_llm"] += matrix_correct
        c_variants["deterministic"] += det_correct

        if (gate_correct or matrix_correct or det_correct) and not static_correct:
            milestone.append(qid)

        rows[qid] = {
            "state": state,
            "needs": needs,
            "contradictions": contradictions,
            "static_correct": static_correct,
            "baseline_iterative_correct": base_iter_correct,
            "gate_llm_correct": gate_correct,
            "matrix_llm_correct": matrix_correct,
            "deterministic_correct": det_correct,
        }

    json.dump(rows, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    total = len(rows)
    print(f"{'fall':<7} {'state':<22} {'statisk':>7} {'baselin':>7} {'grind':>6} {'matris':>6} {'det.':>5}")
    for qid, r in rows.items():
        print(
            f"{qid:<7} {r['state']:<22} {str(r['static_correct']):>7} "
            f"{str(r['baseline_iterative_correct']):>7} {str(r['gate_llm_correct']):>6} "
            f"{str(r['matrix_llm_correct']):>6} {str(r['deterministic_correct']):>5}"
        )
    print(f"\nA: grinden hindrade gissning i {a_count}/{total} fall")
    print(f"B: READY_TO_SYNTHESIZE i {b_ready}/{total} fall")
    print(f"C: korrekta slutsatser — grind-LLM {c_variants['gate_llm']}, matris-LLM {c_variants['matrix_llm']}, deterministisk {c_variants['deterministic']}")
    print(f"milstolpe (någon variant rätt där statisk är fel): {milestone if milestone else 'inte nådd'}")
    print(f"skrivet: {OUT}")


if __name__ == "__main__":
    main()

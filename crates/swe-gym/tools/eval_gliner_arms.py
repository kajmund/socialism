#!/usr/bin/env python3
"""The four-arm experiment (docs/architecture/gliner2-jevspan-evaluation
.md, D2): existing generator vs GLiNER2 generic labels vs GLiNER2
need-driven labels vs the union -> selective JEV verification. Strict
span matching (string-level; the preliminary matching result stands
until offsets are available). The g4-05 improvement is measured
separately at the end.

Run: /tmp/gliner_venv/bin/python crates/swe-gym/tools/eval_gliner_arms.py
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_gliner_testset import spans_of, LABEL_MAP  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
TESTSET = B / "gliner_testset.json"
GOLDEN = B / "golden_v4.json"
BENCH = B / "bench_real_v2.json"
OUT = B / "gliner_arms.json"

GENERIC_LABELS = list(LABEL_MAP.values())


def normalize(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def strict_metrics(found, gold):
    """found: set of normalized spans; gold: set of normalized spans."""
    tp = len(found & gold)
    fp = len(found - gold)
    fn = len(gold - found)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return tp, fp, fn, prec, rec, f1


def main():
    cases = json.load(open(TESTSET, encoding="utf-8"))["cases"]
    texts = {}
    for q in json.load(open(BENCH, encoding="utf-8"))["questions"]:
        texts.update(q.get("texts", {}))

    from gliner2 import AutoExtractor
    model = AutoExtractor.from_pretrained("fastino/gliner2.5-multi-v1")

    def run_arm(labels_per_case):
        found_all = []
        per_case = {}
        for case in cases:
            labels = labels_per_case(case)
            raw = model.extract_entities(case["text"], entity_types=labels,
                                         threshold=0.3, format_results=False)
            found = set()
            for entry in raw.get("entities", []):
                for label, spans in entry.items():
                    for span in spans:
                        found.add(normalize(span))
            per_case[case["chunk"]] = sorted(found)
            found_all.append((found, case))
        return found_all, per_case

    # Arm 0: the existing deterministic generator.
    arm0 = []
    for case in cases:
        gold = {normalize(g["span"]) for g in case["gold"]}
        det = {normalize(s) for _, s in spans_of(case["text"])}
        arm0.append((det, case))
    tp0 = sum(len(f & {normalize(g["span"]) for g in c["gold"]}) for f, c in arm0)
    fp0 = sum(len(f - {normalize(g["span"]) for g in c["gold"]}) for f, c in arm0)
    fn0 = sum(len({normalize(g["span"]) for g in c["gold"]} - f) for f, c in arm0)
    p0 = tp0 / (tp0 + fp0) if tp0 + fp0 else 0.0
    r0 = tp0 / (tp0 + fn0) if tp0 + fn0 else 0.0
    f10 = 2 * p0 * r0 / (p0 + r0) if p0 + r0 else 0.0

    # Arm 1: generic labels.
    arm1, per1 = run_arm(lambda c: GENERIC_LABELS)
    tp1 = fp1 = fn1 = 0
    for f, c in arm1:
        gold = {normalize(g["span"]) for g in c["gold"]}
        t, fp, fn, _, _, _ = strict_metrics(f, gold)
        tp1 += t; fp1 += fp; fn1 += fn
    p1 = tp1 / (tp1 + fp1) if tp1 + fp1 else 0.0
    r1 = tp1 / (tp1 + fn1) if tp1 + fn1 else 0.0
    f11 = 2 * p1 * r1 / (p1 + r1) if p1 + r1 else 0.0

    # Arm 2: need-driven labels (the chunk's own need types, max 3).
    arm2, per2 = run_arm(lambda c: c["need_labels"])
    tp2 = fp2 = fn2 = 0
    for f, c in arm2:
        gold = {normalize(g["span"]) for g in c["gold"]}
        t, fp, fn, _, _, _ = strict_metrics(f, gold)
        tp2 += t; fp2 += fp; fn2 += fn
    p2 = tp2 / (tp2 + fp2) if tp2 + fp2 else 0.0
    r2 = tp2 / (tp2 + fn2) if tp2 + fn2 else 0.0
    f12 = 2 * p2 * r2 / (p2 + r2) if p2 + r2 else 0.0

    # Arm 3: union of arm-2 spans and the deterministic spans; the
    # verified-fact coverage (JEV verification is the selective rule's
    # job — here we measure the union's coverage of gold spans, the
    # input to that verification).
    tp3 = fp3 = fn3 = 0
    for (f2, c), (f0, _) in zip(arm2, arm0):
        gold = {normalize(g["span"]) for g in c["gold"]}
        union = f2 | f0
        t, fp, fn, _, _, _ = strict_metrics(union, gold)
        tp3 += t; fp3 += fp; fn3 += fn
    p3 = tp3 / (tp3 + fp3) if tp3 + fp3 else 0.0
    r3 = tp3 / (tp3 + fn3) if tp3 + fn3 else 0.0
    f13 = 2 * p3 * r3 / (p3 + r3) if p3 + r3 else 0.0

    print(f"{'arm':<34} {'prec':>6} {'rec':>6} {'F1':>6} {'tp':>4} {'fp':>4} {'fn':>4}")
    for name, tp, fp, fn, p, r, f in [
        ("0: befintlig generator", tp0, fp0, fn0, p0, r0, f10),
        ("1: GLiNER2 generella etiketter", tp1, fp1, fn1, p1, r1, f11),
        ("2: GLiNER2 behovsstyrda etiketter", tp2, fp2, fn2, p2, r2, f12),
        ("3: union → (JEV-verifiering)", tp3, fp3, fn3, p3, r3, f13),
    ]:
        print(f"{name:<34} {p:>6.2f} {r:>6.2f} {f:>6.2f} {tp:>4} {fp:>4} {fn:>4}")

    # The g4-05 question: does GLiNER2 supply the missing candidate
    # spans for the risk clauses?
    print("\n=== g4-05: GLiNER2-spann för riskklausulerna ===")
    g4 = {q["id"]: q for q in json.load(open(GOLDEN, encoding="utf-8"))["questions"]}
    q5 = g4["g4-05"]
    for chunk in q5["evidence"]:
        text = texts[chunk]
        need_labels = ["Avgångsvederlag", "Uppsägningstid", "Uppsägningsvillkor"]
        raw = model.extract_entities(text, entity_types=need_labels,
                                     threshold=0.3, format_results=False)
        found = []
        for entry in raw.get("entities", []):
            for label, spans in entry.items():
                found.extend(spans)
        print(f"  {chunk}: {found}")

    json.dump(
        {"arms": {
            "arm0": {"precision": p0, "recall": r0, "f1": f10},
            "arm1": {"precision": p1, "recall": r1, "f1": f11},
            "arm2": {"precision": p2, "recall": r2, "f1": f12},
            "arm3": {"precision": p3, "recall": r3, "f1": f13},
        }},
        open(OUT, "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=2,
    )
    print(f"\nskrivet: {OUT}")


if __name__ == "__main__":
    main()

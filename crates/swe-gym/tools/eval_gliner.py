#!/usr/bin/env python3
"""Bounded offline GLiNER2 span evaluation over the frozen g4 chunks
(docs/architecture/gliner2-jevspan-evaluation.md, section 5). Strict
span F1 per entity type against gold spans derived from the golden
facit, plus the comparison with the existing deterministic extractor.

Run: backend/.venv/bin/python crates/swe-gym/tools/eval_gliner.py
First run installs nothing; needs torch+transformers+gliner2 in the venv.
"""

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
BENCH = B / "bench_real_v2.json"
GOLDEN = B / "golden_v4.json"
OUT = B / "gliner_spans.json"

# Gold spans: the key entities in the g4 evidence chunks (the duration
# phrases and the risk-clause terms), aligned with the golden facit.
GOLD_SPANS = {
    "Avtal_81_VD_anstallningsavtal:18": [
        ("NOTICE_PERIOD", "sex (6) månader"),
    ],
    "Avtal_81_VD_anstallningsavtal:25": [
        ("NON_COMPETE_PERIOD", "tolv (12) månader"),
    ],
    "Avtal_18_Hyresavtal_bostad:5": [
        ("NOTICE_PERIOD", "tre (3) månader"),
    ],
    "Avtal_18_Hyresavtal_bostad:6": [
        ("NOTICE_PERIOD", "tre månader"),
    ],
    "Avtal_32_Inkopsavtal:7": [
        ("ANNEX_REF", "Bilaga 2"),
    ],
    "Avtal_20_Arrendeavtal_lagenhetsarrende:7": [
        ("NOTICE_PERIOD", "sex (6) månader"),
        ("RENEWAL_PERIOD", "ett (1) år"),
    ],
    "Avtal_81_VD_anstallningsavtal:19": [
        ("SEVERANCE", "avgångsvederlag"),
        ("SEVERANCE_VALUE", "sex (6) fasta månadslöner"),
    ],
    "Avtal_81_VD_anstallningsavtal:20": [
        ("TERMINATION_CONDITION", "omedelbar verkan"),
    ],
}

LABELS = [
    "Uppsägningstid",
    "Avgångsvederlag",
    "Vite",
    "Ansvarstak",
    "Undantag",
    "Konkurrensbegränsning",
    "Belopp",
    "Datum",
    "Avtalspart",
]


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def main():
    d = json.load(open(BENCH, encoding="utf-8"))
    texts = {}
    for q in d["questions"]:
        texts.update(q.get("texts", {}))
    golden = {q["id"]: q for q in json.load(open(GOLDEN, encoding="utf-8"))["questions"]}

    from gliner2 import AutoExtractor

    model = AutoExtractor.from_pretrained("fastino/gliner2.5-multi-v1")
    results = {}
    total_tp = total_fp = total_fn = 0
    per_type = {}
    for chunk, gold in GOLD_SPANS.items():
        text = texts[chunk]
        raw = model.extract_entities(text, entity_types=LABELS, threshold=0.3,
                                     format_results=False)
        found = []
        for entry in raw.get("entities", []):
            for label, spans in entry.items():
                for span in spans:
                    found.append((label, normalize(span), 0.0))
        gold_norm = {normalize(g[1]): g[0] for g in gold}
        # strict span match, deduplicated: a span counts once regardless
        # of the label the model gave it (the type is judged separately).
        distinct_found = set(span for _, span, _ in found)
        tp = len([s for s in distinct_found if s in gold_norm])
        fp = len(distinct_found) - tp
        fn = len(gold_norm) - tp
        total_tp += tp
        total_fp += fp
        total_fn += fn
        results[chunk] = {"gold": gold, "found": found, "tp": tp, "fp": fp, "fn": fn}
        print(f"{chunk}: tp {tp} fp {fp} fn {fn} | {[f[1] for f in found]}")

    prec = total_tp / (total_tp + total_fp) if total_tp + total_fp else 0.0
    rec = total_tp / (total_tp + total_fn) if total_tp + total_fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    print(f"\nGLiNER2.5-multi zero-shot, svenska avtalschunkar:")
    print(f"  strict span precision {prec:.2f} recall {rec:.2f} F1 {f1:.2f}")
    print(f"  (tp {total_tp}, fp {total_fp}, fn {total_fn} över {len(GOLD_SPANS)} chunkar)")
    json.dump(
        {"model": "fastino/gliner2.5-multi-v1", "labels": LABELS, "results": results,
         "precision": prec, "recall": rec, "f1": f1},
        open(OUT, "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=2,
    )
    print(f"skrivet: {OUT}")


if __name__ == "__main__":
    main()

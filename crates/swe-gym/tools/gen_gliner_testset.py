#!/usr/bin/env python3
"""The independent span test set for the four-arm GLiNER2 experiment
(docs/architecture/gliner2-jevspan-evaluation.md, D2): 30 chunks sampled
from the corpus with deterministically derived gold spans (regex +
document structure — never model output) and need-driven label specs.

Output: benchmarks/gliner_testset.json
"""

import json
import re
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_golden_v2 import DURATION_RE, WORD_NUMS, extract_duration  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
BENCH = B / "bench_real_v2.json"
OUT = B / "gliner_testset.json"

TERM_RE = re.compile(
    r"upps(ä|a)g|s(ä|a)ger upp|s(ä|a)gs upp|s(ä|a)gas upp|avtalstid",
    re.IGNORECASE,
)
MONEY_RE = re.compile(r"\[\s*(?:Belopp|[0-9][0-9\s\u00a0]*)\s*(?:kr|kronor)?\s*\]", re.IGNORECASE)
DATE_RE = re.compile(r"\[\d{4}-\d{2}-\d{2}\]")

SEVERANCE_WORDS = ["avgångsvederlag"]
PENALTY_WORDS = ["vite", "vitesklausul", "förseningsavgift"]
CAP_WORDS = ["ansvarstak", "ansvarsbegränsning", "begränsas till", "skadeståndsansvar"]
EXCEPTION_WORDS = ["undantag", "om inte", "med undantag för"]
PARTY_WORDS = ["DevBrains AB", "Ljusgård Design AB", "Fastighets AB Kvarnberget", "Jonas Ekholm"]


def spans_of(text):
    """Deterministic gold spans — the same mechanism as the existing
    generator, NOT model output."""
    spans = []
    for m in DURATION_RE.finditer(text):
        word, digits, plain = m.group(1), m.group(2), m.group(3)
        if word and word.lower() in WORD_NUMS:
            pass
        elif digits or plain:
            pass
        else:
            continue
        span = re.sub(r"[\[\]]", "", m.group(0)).strip()
        label = "NOTICE_PERIOD" if TERM_RE.search(text) else "PERIOD"
        spans.append((label, span))
    if "avgångsvederlag" in text.lower():
        spans.append(("SEVERANCE", "avgångsvederlag"))
    if re.search(r"omedelbar verkan", text, re.IGNORECASE):
        spans.append(("TERMINATION_CONDITION", "omedelbar verkan"))
    if re.search(r"vite", text, re.IGNORECASE):
        spans.append(("PENALTY", "vite"))
    if re.search(r"ansvars(?:begränsning|tak)", text, re.IGNORECASE):
        m = re.search(r"ansvars(?:begränsning|tak)", text, re.IGNORECASE)
        spans.append(("LIABILITY_CAP", m.group(0)))
    if re.search(r"undantag", text, re.IGNORECASE):
        spans.append(("EXCEPTION", "undantag"))
    for w in PARTY_WORDS:
        if w in text:
            spans.append(("PARTY", w))
    for m in MONEY_RE.finditer(text):
        spans.append(("MONEY", m.group(0)))
    for m in DATE_RE.finditer(text):
        spans.append(("DATE", m.group(0)))
    return spans


LABEL_MAP = {
    "NOTICE_PERIOD": "Uppsägningstid",
    "SEVERANCE": "Avgångsvederlag",
    "TERMINATION_CONDITION": "Uppsägningsvillkor",
    "PENALTY": "Vite",
    "LIABILITY_CAP": "Ansvarstak",
    "EXCEPTION": "Undantag",
    "PARTY": "Avtalspart",
    "MONEY": "Belopp",
    "DATE": "Datum",
    "PERIOD": "Tidsperiod",
}


def main():
    d = json.load(open(BENCH, encoding="utf-8"))
    texts = {}
    for q in d["questions"]:
        texts.update(q.get("texts", {}))

    # Sample 30 chunks with at least one deterministic gold span, in
    # deterministic order (seeded), excluding nothing — independent of
    # the g4 evaluation chunks.
    rng = random.Random(42)
    candidates = [c for c in texts if spans_of(texts[c])]
    rng.shuffle(candidates)
    picked = candidates[:30]

    cases = []
    for c in picked:
        gold = spans_of(texts[c])
        # Need-driven labels: the entity types the chunk's facts need
        # (max 3), derived from the gold types — what a NEED would ask.
        need_labels = sorted({LABEL_MAP[t] for t, _ in gold})[:3]
        cases.append({
            "chunk": c,
            "text": texts[c],
            "gold": [{"type": t, "span": s} for t, s in gold],
            "need_labels": need_labels,
        })

    json.dump({"version": 1, "cases": cases}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"testset: {len(cases)} chunkar, "
          f"{sum(len(c['gold']) for c in cases)} guldspann, "
          f"{sum(len(c['need_labels']) for c in cases)} behovsstyrda etiketter totalt")
    print(f"skrivet: {OUT}")


if __name__ == "__main__":
    main()

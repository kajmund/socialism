#!/usr/bin/env python3
"""Controlled dependency cases (docs/SWE_Sweycoins_v2.md 23).

The corpus probe showed the 50 template contracts carry few chunk-level
internal references (0 resolvable 'punkt N', 1 annex heading, 1 clean
forlang->uppsagning chain) — recorded honestly. The controlled cases
therefore center on the dependency the corpus DOES support: cross-
document comparisons, where the conclusion requires evidence from every
named document, plus the two internal chains that exist and negative
controls where further retrieval adds nothing.

Output: benchmarks/golden_v3.json + golden_v3_verify.txt
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_golden_v2 import extract_duration  # noqa: E402


def months(d):
    n, unit = d.split(" ", 1)
    n = int(n)
    return n * {"år": 12, "månad": 1, "månader": 1, "vecka": 0.25, "veckor": 0.25, "dag": 1 / 30, "dagar": 1 / 30}.get(unit, 0)

REPO = Path(__file__).resolve().parents[3]
B = REPO / "crates" / "swe-gym" / "benchmarks"
BENCH = B / "bench_real_v2.json"
OUT = B / "golden_v3.json"
VERIFY = B / "golden_v3_verify.txt"

FORLANG_RE = re.compile(r"förl(ä|a)ng", re.IGNORECASE)
UPPSAG_RE = re.compile(r"upps(ä|a)gningstid|s(ä|a)gs upp", re.IGNORECASE)


def main():
    d = json.load(open(BENCH, encoding="utf-8"))
    texts = {}
    for q in d["questions"]:
        texts.update(q.get("texts", {}))
    docs = {}
    for c, t in texts.items():
        docs.setdefault(c.split(":")[0], {})[c] = t

    # Duration data per document (for cross-document comparisons).
    durations = {}
    for doc, chunks in docs.items():
        for c, t in chunks.items():
            if UPPSAG_RE.search(t) or FORLANG_RE.search(t):
                dur = extract_duration(t)
                if dur:
                    durations.setdefault(doc, []).append((c, dur))

    cases = []
    verify = []

    def add(case_id, doc, question, evidence, conclusion, note, positive):
        cases.append({
            "id": f"g3-{case_id:02d}",
            "doc": doc,
            "question": question,
            "evidence": sorted(evidence),
            "conclusion": conclusion,
            "positive": positive,
            "note": note,
        })
        verify.append(f"=== g3-{case_id:02d} [{'+' if positive else '-'}] {question}\n    slutsats: {conclusion}\n")
        for c in sorted(evidence):
            verify.append(f"    evidens {c}: {texts[c][:160]!r}")
        verify.append("")

    case_id = 0
    # Positive: cross-document comparisons (the conclusion needs all docs).
    ranked = sorted(durations.items(), key=lambda kv: len(kv[1]))
    groups = []
    i = 0
    while i + 2 < len(ranked) and len(groups) < 6:
        group = ranked[i : i + 3]
        docs_in = [g[0] for g in group]
        values = {g[0]: months(g[1][0][1]) for g in group if g[1]}
        if len(values) == 3:
            longest = max(values, key=lambda k: values[k])
            evidence = [g[1][0][0] for g in group]
            groups.append((docs_in, longest, values, evidence))
        i += 1

    for docs_in, longest, values, evidence in groups:
        case_id += 1
        add(
            case_id,
            docs_in[0],
            f"Vilket av dessa dokument har längst uppsägningstid? ({', '.join(docs_in)})",
            evidence,
            longest,
            "korsdokumentberoende: slutsatsen kräver evidens från alla tre dokumenten",
            True,
        )

    # Positive: the internal chain that exists (Avtal_34 forlang->uppsagning).
    doc = "Avtal_34_Aterforsaljaravtal"
    if doc in docs:
        primary = [c for c, t in docs[doc].items() if FORLANG_RE.search(t) and UPPSAG_RE.search(t)]
        target = [c for c, t in docs[doc].items() if UPPSAG_RE.search(t) and c not in primary]
        if primary and target:
            case_id += 1
            add(
                case_id,
                doc,
                f"Hur länge kan {doc} som längst vara bindande?",
                primary + target,
                f"{docs[doc][primary[0]][:80]!r} + {docs[doc][target[0]][:80]!r}",
                "intern kedja: förlängningsklausulen villkoras av uppsägningsklausulen",
                True,
            )

    # Negative controls: self-contained single-clause questions.
    self_contained = [
        (doc, c)
        for doc, chunks in docs.items()
        for c, t in chunks.items()
        if re.match(r"^\s*\d+\.\d*\s", t) and not FORLANG_RE.search(t)
    ][:20]
    for doc, c in self_contained:
        if case_id >= 12:
            break
        case_id += 1
        add(
            case_id,
            doc,
            f"Vad gäller enligt {doc} i {texts[c].strip().splitlines()[0][:50]}?",
            [c],
            texts[c][:120],
            "negativ kontroll: svaret är självständigt — extra retrieval tillför inget",
            False,
        )

    payload = {"version": 1, "questions": cases}
    json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    VERIFY.write_text("\n".join(verify), encoding="utf-8")
    pos = sum(1 for q in cases if q["positive"])
    print(f"genererade {len(cases)} fall ({pos} positiva, {len(cases) - pos} negativa)")


if __name__ == "__main__":
    main()

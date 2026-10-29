#!/usr/bin/env python3
"""Generate the Research Gym golden questions (docs/SWE_Sweycoins_v2.md 19).

Deterministic structural extraction — clause keywords + duration regex over
the raw contract chunk texts. The facit (evidence + conclusion) is derived
from document structure, NOT from JEV, LLM or embeddings, so it is
independent of the capabilities being measured. Every question carries its
evidence chunk texts in a human-verification log.

Output: benchmarks/golden_v2.json + benchmarks/golden_v2_verify.txt
"""

import json
import re
import sys
from pathlib import Path

BENCH = Path("crates/swe-gym/benchmarks/bench_real_v2.json")
OUT = Path("crates/swe-gym/benchmarks/golden_v2.json")
VERIFY = Path("crates/swe-gym/benchmarks/golden_v2_verify.txt")

CLAUSES = {
    "uppsägningstid": [r"upps(ä|a)gningstid", r"upps(ä|a)gning"],
    "automatisk förlängning": [r"förl(ä|a)ng"],
    "sekretess": [r"sekretess|konfidentialitet"],
    "skadestånd": [r"skadest(å|a)nd"],
    "force majeure": [r"force majeure"],
    "tillämplig lag": [r"till(ä|a)mplig lag|lagsval"],
    "överlåtelse": [r"överl(å|a)telse"],
}

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
        number = WORD_NUMS[word.lower()]
    elif digits:
        number = int(digits)
    elif plain:
        number = int(plain)
    else:
        return None
    return f"{number} {m.group(4).lower()}"


def load_documents():
    bench = json.load(open(BENCH, encoding="utf-8"))
    docs = {}
    for q in bench["questions"]:
        for chunk in q["chunks"]:
            doc = chunk.split(":")[0]
            docs.setdefault(doc, {})[chunk] = q["texts"].get(chunk, "")
    return docs


def clause_hits(docs, clause_keywords):
    """chunk -> first keyword match position per document."""
    hits = {}
    for doc, chunks in docs.items():
        for chunk, text in chunks.items():
            if any(re.search(kw, text, re.IGNORECASE) for kw in clause_keywords):
                hits.setdefault(doc, []).append(chunk)
    return hits


def main():
    docs = load_documents()
    doc_names = sorted(docs.keys())
    per_clause = {}
    for clause, keywords in CLAUSES.items():
        per_clause[clause] = clause_hits(docs, keywords)

    questions = []
    verify = []
    qid = 0

    def add(category, question, documents, evidence, conclusion, conclusion_evidence):
        nonlocal qid
        qid += 1
        questions.append(
            {
                "id": f"g2-{qid:02d}",
                "category": category,
                "question": question,
                "documents": documents,
                "evidence": sorted(set(evidence)),
                "conclusion": conclusion,
                "conclusion_evidence": conclusion_evidence,
            }
        )
        verify.append(
            f"=== {qid:02d} [{category}] {question}\n"
            f"    slutsats: {conclusion}\n"
        )
        for c in sorted(set(evidence)):
            text = docs[c.split(":")[0]][c][:220].replace("\n", " ")
            verify.append(f"    evidens {c}: {text}")
        verify.append("")

    # --- 1. Evidenssökning: 5 positiva + 5 negativa -------------------------
    pos_plans = [
        ("uppsägningstid", "Avtal_05_Konsultavtal"),
        ("sekretess", "Avtal_06_Sekretessavtal_ensidigt_NDA"),
        ("automatisk förlängning", "Avtal_17_Hyresavtal_lokal"),
        ("force majeure", "Avtal_30_Ramavtal_tjanster"),
        ("skadestånd", "Avtal_47_Programvarulicensavtal"),
        ("tillämplig lag", "Avtal_31_Leveransavtal"),
        ("överlåtelse", "Avtal_30_Ramavtal_tjanster"),
    ]
    for clause, doc in pos_plans:
        if doc not in per_clause[clause] or not per_clause[clause][doc]:
            print(f"WARN: {doc} saknar {clause} — hoppar", file=sys.stderr)
            continue
        add(
            "evidenssökning",
            f"Innehåller {doc} en klausul om {clause}?",
            [doc],
            per_clause[clause][doc],
            "ja",
            f"{doc} innehåller {len(per_clause[clause][doc])} chunk(ar) med klausulen",
        )

    neg_plans = [
        ("sekretess", "Avtal_15_Bonusavtal"),
        ("force majeure", "Avtal_11_Distansarbetsavtal"),
        ("automatisk förlängning", "Avtal_02_Provanstallningsavtal"),
        ("skadestånd", "Avtal_15_Bonusavtal"),
        ("tillämplig lag", "Avtal_06_Sekretessavtal_ensidigt_NDA"),
    ]
    for clause, doc in neg_plans:
        if doc not in docs:
            continue
        if doc in per_clause[clause] and per_clause[clause][doc]:
            print(f"WARN: {doc} HAR {clause} — negativ fråga ogiltig", file=sys.stderr)
            continue
        add(
            "evidenssökning",
            f"Innehåller {doc} en klausul om {clause}?",
            [doc],
            [],
            "nej",
            f"{doc} innehåller ingen {clause}-klausul",
        )

    # --- 2. Korsdokumentanalys: vilka av fyra dokument har klausulen? --------
    cross_plans = [
        (
            "tillämplig lag",
            [
                "Avtal_31_Leveransavtal",
                "Avtal_51_Anvandarvillkor_webbplats_app",
                "Avtal_15_Bonusavtal",
                "Avtal_11_Distansarbetsavtal",
            ],
        ),
        (
            "överlåtelse",
            [
                "Avtal_42_Factoringavtal",
                "Avtal_30_Ramavtal_tjanster",
                "Avtal_06_Sekretessavtal_ensidigt_NDA",
                "Avtal_15_Bonusavtal",
            ],
        ),
        (
            "sekretess",
            [
                "Avtal_06_Sekretessavtal_ensidigt_NDA",
                "Avtal_05_Konsultavtal",
                "Avtal_15_Bonusavtal",
                "Avtal_11_Distansarbetsavtal",
            ],
        ),
        (
            "force majeure",
            [
                "Avtal_05_Konsultavtal",
                "Avtal_17_Hyresavtal_lokal",
                "Avtal_01_Tillsvidareanstallningsavtal",
                "Avtal_03_Visstidsanstallning",
            ],
        ),
        (
            "automatisk förlängning",
            [
                "Avtal_17_Hyresavtal_lokal",
                "Avtal_20_Arrendeavtal_lagenhetsarrende",
                "Avtal_02_Provanstallningsavtal",
                "Avtal_13_Avgangsvederlagsavtal",
            ],
        ),
        (
            "skadestånd",
            [
                "Avtal_01_Tillsvidareanstallningsavtal",
                "Avtal_05_Konsultavtal",
                "Avtal_15_Bonusavtal",
                "Avtal_03_Visstidsanstallning",
            ],
        ),
        (
            "uppsägningstid",
            [
                "Avtal_05_Konsultavtal",
                "Avtal_01_Tillsvidareanstallningsavtal",
                "Avtal_15_Bonusavtal",
                "Avtal_02_Provanstallningsavtal",
            ],
        ),
    ]
    for clause, group in cross_plans:
        with_docs = [d for d in group if per_clause[clause].get(d)]
        evidence = [c for d in with_docs for c in per_clause[clause][d]]
        if not with_docs:
            continue
        add(
            "korsdokument",
            f"Vilka av dessa dokument innehåller en klausul om {clause}? ({', '.join(group)})",
            group,
            evidence,
            ", ".join(with_docs),
            f"{len(with_docs)} av {len(group)} dokument innehåller klausulen",
        )

    # --- 3. Resonemang/syntes: uppsägningstid-värden -------------------------
    duration_docs = {}
    for doc in doc_names:
        for chunk in per_clause.get("uppsägningstid", {}).get(doc, []):
            text = docs[doc][chunk]
            d = extract_duration(text)
            if d:
                duration_docs.setdefault(doc, []).append((chunk, d))

    single_plans = [
        "Avtal_05_Konsultavtal",
        "Avtal_01_Tillsvidareanstallningsavtal",
        "Avtal_17_Hyresavtal_lokal",
        "Avtal_11_Distansarbetsavtal",
        "Avtal_20_Arrendeavtal_lagenhetsarrende",
    ]
    for doc in single_plans:
        entries = duration_docs.get(doc, [])
        if not entries:
            continue
        chunk, d = entries[0]
        add(
            "resonemang/syntes",
            f"Hur lång är uppsägningstiden enligt {doc}?",
            [doc],
            [c for c, _ in entries],
            d,
            f"uppsägningstid {d} (chunk {chunk})",
        )

    # Jämförelsefrågor: längst uppsägningstid av tre dokument
    def months(duration):
        n, unit = duration.split(" ", 1)
        n = int(n)
        return n * {"år": 12, "månad": 1, "månader": 1, "vecka": 0.25, "veckor": 0.25, "dag": 1 / 30, "dagar": 1 / 30}.get(unit, 0)

    comparables = [d for d in doc_names if d in duration_docs]
    for i in range(0, min(5, len(comparables) - 2)):
        group = comparables[i : i + 3]
        values = {d: months(duration_docs[d][0][1]) for d in group}
        longest = max(group, key=lambda d: values[d])
        evidence = [c for d in group for c, _ in duration_docs[d]]
        add(
            "resonemang/syntes",
            f"Vilket av dessa dokument har längst uppsägningstid? ({', '.join(group)})",
            group,
            evidence,
            longest,
            f"längst uppsägningstid: {longest} ({duration_docs[longest][0][1]}), "
            + "; ".join(f"{d}: {duration_docs[d][0][1]}" for d in group),
        )

    cross_extra = [
        (
            "force majeure",
            [
                "Avtal_30_Ramavtal_tjanster",
                "Avtal_31_Leveransavtal",
                "Avtal_15_Bonusavtal",
                "Avtal_03_Visstidsanstallning",
            ],
        ),
        (
            "skadestånd",
            [
                "Avtal_32_Inkopsavtal",
                "Avtal_47_Programvarulicensavtal",
                "Avtal_15_Bonusavtal",
                "Avtal_02_Provanstallningsavtal",
            ],
        ),
        (
            "tillämplig lag",
            [
                "Avtal_32_Inkopsavtal",
                "Avtal_02_Provanstallningsavtal",
                "Avtal_06_Sekretessavtal_ensidigt_NDA",
                "Avtal_15_Bonusavtal",
            ],
        ),
        (
            "överlåtelse",
            [
                "Avtal_17_Hyresavtal_lokal",
                "Avtal_20_Arrendeavtal_lagenhetsarrende",
                "Avtal_06_Sekretessavtal_ensidigt_NDA",
                "Avtal_11_Distansarbetsavtal",
            ],
        ),
        (
            "uppsägningstid",
            [
                "Avtal_01_Tillsvidareanstallningsavtal",
                "Avtal_17_Hyresavtal_lokal",
                "Avtal_15_Bonusavtal",
                "Avtal_03_Visstidsanstallning",
            ],
        ),
    ]
    for clause, group in cross_extra:
        with_docs = [d for d in group if per_clause[clause].get(d)]
        evidence = [c for d in with_docs for c in per_clause[clause][d]]
        if 0 < len(with_docs) < len(group):
            add(
                "korsdokument",
                f"Vilka av dessa dokument innehåller en klausul om {clause}? ({', '.join(group)})",
                group,
                evidence,
                ", ".join(with_docs),
                f"{len(with_docs)} av {len(group)} dokument innehåller klausulen",
            )

    # Rebalance to 30 if a plan dropped out: pad with more single-duration questions.
    for doc in doc_names:
        if len(questions) >= 32:
            break
        if doc in duration_docs and all(q["documents"] != [doc] for q in questions):
            entries = duration_docs[doc]
            chunk, d = entries[0]
            add(
                "resonemang/syntes",
                f"Hur lång är uppsägningstiden enligt {doc}?",
                [doc],
                [c for c, _ in entries],
                d,
                f"uppsägningstid {d} (chunk {chunk})",
            )

    # Exactly 30, evenly split across the three categories (10 each).
    by_cat = {}
    for q in questions:
        by_cat.setdefault(q["category"], []).append(q)
    trimmed = []
    for cat in ("evidenssökning", "korsdokument", "resonemang/syntes"):
        trimmed.extend(by_cat.get(cat, [])[:10])
    questions = trimmed

    payload = {"version": 1, "questions": questions}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    VERIFY.write_text("\n".join(verify), encoding="utf-8")
    cats = {}
    for q in questions:
        cats[q["category"]] = cats.get(q["category"], 0) + 1
    print(f"genererade {len(questions)} frågor: {cats}")
    print(f"verifikationslogg: {VERIFY}")


if __name__ == "__main__":
    main()

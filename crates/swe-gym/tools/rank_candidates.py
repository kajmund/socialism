#!/usr/bin/env python3
"""Rank the Research Gym candidates by embedding similarity and freeze the
candidate set + ranks (docs/SWE_Sweycoins_v2.md 19). The retrieval
capability's ordering for the 30 new questions, computed once and frozen.

Usage: backend/.venv/bin/python crates/swe-gym/tools/rank_candidates.py
(needs OPENAI_API_KEY, EMBEDDING_MODEL, EMBEDDING_BASE_URL from backend/.env)

Outputs: benchmarks/golden_v2_candidates.json + golden_v2_ranks.json
"""

import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from embed_analysis import CACHE, embed, env_value  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
BENCH = REPO / "crates" / "swe-gym" / "benchmarks" / "bench_real_v2.json"
GOLDEN = REPO / "crates" / "swe-gym" / "benchmarks" / "golden_v2.json"
OUT_CAND = REPO / "crates" / "swe-gym" / "benchmarks" / "golden_v2_candidates.json"
OUT_RANKS = REPO / "crates" / "swe-gym" / "benchmarks" / "golden_v2_ranks.json"


def main():
    api_key = env_value("OPENAI_API_KEY", REPO / "backend" / ".env")
    if not api_key:
        print("OPENAI_API_KEY saknas", file=sys.stderr)
        sys.exit(1)
    model = env_value("EMBEDDING_MODEL", REPO / "backend" / ".env", "text-embedding-3-large")
    base_url = env_value("EMBEDDING_BASE_URL", REPO / "backend" / ".env", "https://api.openai.com/v1")

    bench = json.load(open(BENCH, encoding="utf-8"))
    golden = json.load(open(GOLDEN, encoding="utf-8"))

    texts = {}
    for q in bench["questions"]:
        for c in q["chunks"]:
            texts[c] = q["texts"].get(c, "")

    cache = json.load(open(CACHE, encoding="utf-8"))

    rng = random.Random(19)
    candidates = {}
    ranks = {}
    to_embed = {}

    for question in golden["questions"]:
        evidence = set(question["evidence"])
        doc_chunks = [
            c for c in texts if c.split(":")[0] in question["documents"] and c not in evidence
        ]
        other_chunks = [
            c for c in texts if c.split(":")[0] not in question["documents"] and c not in evidence
        ]
        rng.shuffle(doc_chunks)
        rng.shuffle(other_chunks)
        distractors = (doc_chunks + other_chunks)[: 24 - len(evidence)]
        cand = sorted(evidence) + distractors
        candidates[question["id"]] = cand
        to_embed[question["id"]] = question["question"]

    # Embed all questions (live) and any missing candidate chunks.
    qids = list(to_embed.keys())
    q_vectors, q_tokens, q_ms = embed([to_embed[q] for q in qids], model, base_url, api_key)

    missing = []
    for qid, cand in candidates.items():
        for c in cand:
            if c not in cache:
                missing.append((qid, c))
    if missing:
        m_vectors, m_tokens, m_ms = embed(
            [texts[c] for _, c in missing], model, base_url, api_key
        )
        for (qid, c), v in zip(missing, m_vectors):
            cache[c] = v

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    for qid, qv in zip(qids, q_vectors):
        cand = candidates[qid]
        ranked = sorted(cand, key=lambda c: -cosine(qv, cache[c]))
        ranks[qid] = ranked

    json.dump({"version": 1, "candidates": candidates}, open(OUT_CAND, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump({"version": 1, "ranks": ranks}, open(OUT_RANKS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"frågor: {len(qids)}, fråge-embeddings: {q_tokens} tokens, {q_ms} ms")
    print(f"candidates: {OUT_CAND}")
    print(f"ranks: {OUT_RANKS}")


if __name__ == "__main__":
    main()

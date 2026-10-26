#!/usr/bin/env python3
"""Embedding information-content analysis for the real clause bench.

Answers the question: do text embeddings carry information about WHERE the
evidence sits — better than blind document order or JEV scores? For each of
the five real questions, ranks the chunks by cosine similarity between the
chunk embedding and the question embedding, and measures how many chunks a
scanner would have to visit (in that order) before all gold evidence is
found. Compares against document order (arm A), JEV-score order, and the
oracle floor.

Usage: backend/.venv/bin/python crates/swe-gym/tools/embed_analysis.py
(needs OPENAI_API_KEY, EMBEDDING_MODEL, EMBEDDING_BASE_URL from backend/.env)

Output: crates/swe-gym/benchmarks/real_embedding_report.json
Embedding cache: crates/swe-gym/benchmarks/real_embeddings.json (gitignored)
"""

from __future__ import annotations

import json
import math
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BENCH = REPO / "crates" / "swe-gym" / "benchmarks" / "bench_real_v2.json"
REPORT = REPO / "crates" / "swe-gym" / "benchmarks" / "real_embedding_report.json"
CACHE = REPO / "crates" / "swe-gym" / "benchmarks" / "real_embeddings.json"


def env_value(name: str, dotenv: Path, fallback: str = "") -> str:
    import os

    value = os.environ.get(name)
    if value:
        return value
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, raw = line.partition("=")
            if key.strip() == name:
                return raw.strip().strip('"')
    return fallback


def embed(texts: list[str], model: str, base_url: str, api_key: str) -> list[list[float]]:
    """Batch-embed texts via the OpenAI-compatible endpoint."""
    embeddings: list[list[float]] = []
    batch_size = 500
    for offset in range(0, len(texts), batch_size):
        batch = texts[offset : offset + batch_size]
        body = json.dumps({"model": model, "input": batch}).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/embeddings",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        rows = sorted(payload["data"], key=lambda row: row["index"])
        embeddings.extend([row["embedding"] for row in rows])
        print(f"  bäddade in {offset + len(batch)}/{len(texts)}")
    return embeddings


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def scans_until_all_evidence(ranked: list[str], evidence: set[str]) -> int | None:
    if not evidence:
        return 0
    found = set()
    for index, chunk in enumerate(ranked, start=1):
        if chunk in evidence:
            found.add(chunk)
            if found == evidence:
                return index
    return None


def main() -> None:
    bench = json.loads(BENCH.read_text(encoding="utf-8"))
    dotenv = REPO / "backend" / ".env"
    api_key = env_value("OPENAI_API_KEY", dotenv)
    if not api_key:
        sys.exit("OPENAI_API_KEY saknas (backend/.env)")
    model = env_value("EMBEDDING_MODEL", dotenv, "text-embedding-3-large")
    base_url = env_value("EMBEDDING_BASE_URL", dotenv, "https://api.openai.com/v1")

    # Union of all chunk texts across the five questions.
    union: dict[str, str] = {}
    for question in bench["questions"]:
        for chunk, text in question["texts"].items():
            union.setdefault(chunk, text)
    chunk_ids = sorted(union)
    print(f"bäddar in {len(chunk_ids)} chunks + {len(bench['questions'])} frågor")

    cache: dict[str, list[float]] = {}
    if CACHE.exists():
        cache = json.loads(CACHE.read_text(encoding="utf-8"))

    missing_chunks = [chunk for chunk in chunk_ids if chunk not in cache]
    if missing_chunks:
        vectors = embed([union[chunk] for chunk in missing_chunks], model, base_url, api_key)
        for chunk, vector in zip(missing_chunks, vectors):
            cache[chunk] = vector
    missing_questions = [
        f"q:{question['id']}"
        for question in bench["questions"]
        if f"q:{question['id']}" not in cache
    ]
    if missing_questions:
        question_texts = [
            question["question"]
            for question in bench["questions"]
            if f"q:{question['id']}" in missing_questions
        ]
        vectors = embed(question_texts, model, base_url, api_key)
        for key, vector in zip(missing_questions, vectors):
            cache[key] = vector
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    report = {"model": model, "questions": []}
    for question in bench["questions"]:
        qid = question["id"]
        evidence = set(question["evidence"])
        chunks = question["chunks"]
        question_vector = cache[f"q:{qid}"]

        ranked_similarity = sorted(
            chunks,
            key=lambda chunk: cosine(cache[chunk], question_vector),
            reverse=True,
        )
        similarity_scans = scans_until_all_evidence(ranked_similarity, evidence)

        fixture = json.loads(
            (
                REPO / "crates" / "swe-gym" / "benchmarks" / "real_fixtures" / f"{qid}.json"
            ).read_text(encoding="utf-8")
        )
        answers = {entry["chunk_id"]: entry for entry in fixture["entries"]}
        ranked_jev = sorted(
            chunks,
            key=lambda chunk: (
                0 if answers[chunk]["choice"] == "fynd" else 1,
                -answers[chunk]["score_bp"],
            ),
        )
        jev_scans = scans_until_all_evidence(ranked_jev, evidence)

        doc_scans = scans_until_all_evidence(chunks, evidence)
        report["questions"].append(
            {
                "id": qid,
                "chunks": len(chunks),
                "evidence": len(evidence),
                "scans_document_order": doc_scans,
                "scans_jev_score_order": jev_scans,
                "scans_similarity_order": similarity_scans,
                "oracle_scans": len(evidence),
            }
        )
        # Annotate the frozen bench with the measured retrieval order, so
        # arm H can scan in similarity order without recomputing anything.
        question["scan_order"] = ranked_similarity
        print(
            f"{qid:<28} doc {doc_scans:>4} | jev {jev_scans:>4} | "
            f"sim {similarity_scans:>4} | orakel {len(evidence)}"
        )
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    BENCH.write_text(json.dumps(bench, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"skrev {REPORT.relative_to(REPO)} och annoterade benchen med scan_order")


if __name__ == "__main__":
    main()

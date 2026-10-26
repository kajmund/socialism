#!/usr/bin/env python3
"""One-shot export: real clause-question bench from the project's own corpus.

Reuses the overgraph_ingest extraction/segmentation and the legal-questions
gold suite: extracts each question's gold documents, segments them into text
units, maps gold spans to units, and freezes everything — chunks, real
texts, facit — into the gym's bench format. Five questions: auto-renewal,
notice-period, liability-cap, confidentiality, liability-secrecy-carveout.

Usage: backend/.venv/bin/python crates/swe-gym/tools/export_real_bench.py
(needs the overgraph package from the backend venv plus python-docx and
pymupdf: uv pip install --python backend/.venv/bin/python python-docx pymupdf)

Output: crates/swe-gym/benchmarks/bench_real_v2.json
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
INGEST = REPO / "experiments" / "overgraph_ingest"
sys.path.insert(0, str(INGEST))

from overgraph_ingest.extraction import extract_file  # noqa: E402
from overgraph_ingest.retrieval.gold import (  # noqa: E402
    GoldSpan,
    matching_spans,
)
from overgraph_ingest.segmentation.structural import segment_document  # noqa: E402

GOLD_DIR = INGEST / "retrieval_gold"
CORPUS = INGEST / "data" / "extra_corpus"
OUT = REPO / "crates" / "swe-gym" / "benchmarks" / "bench_real_v2.json"

QUESTION_IDS = (
    "auto-renewal",
    "notice-period",
    "liability-cap",
    "confidentiality",
    "liability-secrecy-carveout",
)

EXTRACTION_VERSION = "gym-export-v1"
SEGMENTATION_VERSION = "gym-export-v1"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_units(relative_path: str) -> list[tuple[str, str]]:
    """Segment one document into (chunk_id, text) pairs."""
    path = CORPUS / relative_path
    if not path.exists():
        sys.exit(f"missing corpus document: {path}")
    data = path.read_bytes()
    extracted = extract_file(
        data,
        relative_path,
        sha256_hex(data),
        extraction_version=EXTRACTION_VERSION,
    )
    if extracted.status != "ok":
        sys.exit(f"extraction failed for {relative_path}: {extracted.error}")
    segmented = segment_document(
        extracted,
        document_version_id=relative_path,
        segmentation_version=SEGMENTATION_VERSION,
    )
    stem = Path(relative_path).stem
    return [(f"{stem}:{unit.sequence}", unit.text) for unit in segmented.units]


def main() -> None:
    questions = []
    for question_id in QUESTION_IDS:
        gold_file = GOLD_DIR / f"{question_id}.json"
        if not gold_file.exists():
            sys.exit(f"missing gold file: {gold_file}")
        gold = json.loads(gold_file.read_text(encoding="utf-8"))
        relevant = [GoldSpan(**item) for item in gold["relevant_units"]]
        hard_negatives = [GoldSpan(**item) for item in gold["hard_negatives"]]
        documents: list[str] = []
        for span in relevant + hard_negatives:
            if span.relative_path not in documents:
                documents.append(span.relative_path)

        chunks: list[str] = []
        evidence: list[str] = []
        texts: dict[str, str] = {}
        matched: set[str] = set()
        for relative_path in documents:
            for chunk_id, text in load_units(relative_path):
                chunks.append(chunk_id)
                texts[chunk_id] = text
                for span in matching_spans(text, relative_path, relevant):
                    evidence.append(chunk_id)
                    matched.add(f"{span.relative_path}::{span.contains}")
                for span in matching_spans(text, relative_path, hard_negatives):
                    print(
                        f"hard-negative chunk (ej evidens) [{question_id}]: "
                        f"{chunk_id}: {span.contains[:60]}"
                    )
        missing = [
            f"{span.relative_path}::{span.contains}"
            for span in relevant
            if f"{span.relative_path}::{span.contains}" not in matched
        ]
        if missing:
            sys.exit(
                f"gold spans without a matching unit ({question_id}, "
                f"{len(missing)}):\n" + "\n".join(missing)
            )
        questions.append(
            {
                "id": question_id,
                # The gold's classify question travels with the bench so the
                # capture tool asks JEV exactly what the gold was curated for.
                "question": str(gold.get("classify_question") or gold.get("query") or ""),
                "required_coverage": len(set(evidence)),
                "chunks": chunks,
                "evidence": sorted(set(evidence)),
                "scan_blind": [],
                "texts": texts,
            }
        )
        print(
            f"{question_id}: {len(documents)} dokument, {len(chunks)} chunks, "
            f"{len(set(evidence))} evidens-chunks"
        )

    bench = {
        "version": 1,
        "name": "swe-gym-real-legal-v1",
        "score_model": "real-jev",
        "tariffs_milli": {"scan": 1000, "deep": 10000},
        # Largest question scans ~900 chunks x 1 coin + deep headroom.
        "total_budget_milli": 2_000_000,
        "questions": questions,
    }
    OUT.write_text(json.dumps(bench, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"skrev {OUT.relative_to(REPO)}: {len(questions)} frågor")


if __name__ == "__main__":
    main()

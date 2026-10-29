"""B4: candidate generation for low-overlap contradiction pairs.

Compares deterministic candidates with embedding and hybrid candidate sets.
Ranking is intentionally not applied; this measures Candidate Recall and
candidate volume before budget/ranking. No Jev call.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
from app.services.research.sufficiency_experiment.claims import extract_claim_candidates
from app.services.research.sufficiency_experiment.gap_cases import (
    candidate_miss_synonyms,
    synonym_compatible_entity,
    synonym_compatible_scope,
    synonym_contradiction_notice,
    synonym_contradiction_semester,
)
from app.services.research.sufficiency_experiment.golden import all_golden_cases
from app.services.research.sufficiency_experiment.pairs import select_pairs
from app.services.research.sufficiency_experiment.segment import segment_evidence
from app.services.research.sufficiency_experiment.types import ExperimentConfig

DEFAULT_OUT = Path("tests/integration/baselines/b4-candidate-recall-v1.json")
STRATEGIES = ("deterministic", "embeddings", "hybrid")
CASE_SPECS = {
    "candidate_miss_synonyms": ("Hundar", "Tamdjur", "contradiction"),
    "synonym_contradiction_semester": ("semesterdagar", "Semesterledigheten", "contradiction"),
    "synonym_contradiction_notice": ("månaders varsel", "Uppsägningstiden", "contradiction"),
    "synonym_compatible_scope": ("2024", "2025", "compatible"),
    "synonym_compatible_entity": ("Hundar", "Katter", "compatible"),
    "late_evidence": ("Högsta domstolen tillämpar", "MOTBEVIS", "contradiction"),
}
EXTRA = {
    "candidate_miss_synonyms": candidate_miss_synonyms(),
    "synonym_contradiction_semester": synonym_contradiction_semester(),
    "synonym_contradiction_notice": synonym_contradiction_notice(),
    "synonym_compatible_scope": synonym_compatible_scope(),
    "synonym_compatible_entity": synonym_compatible_entity(),
}


def _claims(case, config):
    passages = segment_evidence(case.evidence, max_chars=config.max_passage_chars)
    return extract_claim_candidates(
        passages, {item.evidence_id: item for item in case.evidence}, config=config
    )[0]


def _expected_pair(claims, left_marker: str, right_marker: str):
    left = next((claim for claim in claims if left_marker in claim.text), None)
    right = next((claim for claim in claims if right_marker in claim.text), None)
    if left is None or right is None:
        return None
    return frozenset((left.claim_id, right.claim_id))


async def _measure(out: Path) -> dict:
    config = ExperimentConfig()
    cases = {case.case_id: case for case in all_golden_cases()}
    cases.update(EXTRA)
    provider = OpenAIEmbeddingProvider.from_settings()
    rows = []
    for case_id, (left_marker, right_marker, expected) in CASE_SPECS.items():
        case = cases[case_id]
        claims = _claims(case, config)
        expected_pair = _expected_pair(claims, left_marker, right_marker)
        arm_rows = {}
        for strategy in STRATEGIES:
            selection = await select_pairs(
                claims,
                case.plan.needs,
                strategy=strategy,  # type: ignore[arg-type]
                config=config,
                embedding_provider=provider if strategy != "deterministic" else None,
            )
            candidate_keys = {
                frozenset((pair.left_claim_id, pair.right_claim_id))
                for pair in selection.candidates
            }
            arm_rows[strategy] = {
                "candidate_recall": expected_pair in candidate_keys
                if expected_pair is not None
                else False,
                "candidates": len(selection.candidates),
                "embedding_calls": selection.embedding_calls,
                "embedding_texts": selection.embedding_texts,
                "latency_ms": round(selection.latency_ms, 1),
            }
        rows.append(
            {
                "case_id": case_id,
                "expected": expected,
                "expected_pair": sorted(expected_pair) if expected_pair else None,
                "arms": arm_rows,
            }
        )
    positives = [row for row in rows if row["expected"] == "contradiction"]
    negatives = [row for row in rows if row["expected"] == "compatible"]
    summary = {}
    for strategy in STRATEGIES:
        summary[strategy] = {
            "candidate_recall_contradiction": round(
                sum(row["arms"][strategy]["candidate_recall"] for row in positives)
                / len(positives),
                3,
            ),
            "candidate_recall_compatible": round(
                sum(row["arms"][strategy]["candidate_recall"] for row in negatives)
                / max(1, len(negatives)),
                3,
            ),
            "mean_candidates": round(
                sum(row["arms"][strategy]["candidates"] for row in rows) / len(rows), 1
            ),
            "embedding_calls": sum(
                row["arms"][strategy]["embedding_calls"] for row in rows
            ),
            "embedding_texts": sum(
                row["arms"][strategy]["embedding_texts"] for row in rows
            ),
        }
    criteria = {
        "hybrid_recall_not_worse": summary["hybrid"]["candidate_recall_contradiction"]
        >= summary["deterministic"]["candidate_recall_contradiction"],
        "hybrid_gains_a_low_overlap_pair": summary["hybrid"]["candidate_recall_contradiction"]
        > summary["deterministic"]["candidate_recall_contradiction"],
        "candidate_volume_bounded": summary["hybrid"]["mean_candidates"]
        <= 10 * summary["deterministic"]["mean_candidates"],
    }
    payload = {
        "measurement": "b4_candidate_recall",
        "note": "Candidate generation only; no ranking, budget or Jev call.",
        "config": asdict(config),
        "embedding_model": provider.model,
        "criteria": criteria,
        "decision": "CANDIDATE_GENERATION_IMPROVED" if all(criteria.values()) else "KEEP_DETERMINISTIC_GENERATION",
        "summary": summary,
        "rows": rows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(json.dumps(payload["criteria"], indent=2), payload["decision"])
    for row in rows:
        print(row["case_id"], row["expected"], {s: row["arms"][s]["candidate_recall"] for s in STRATEGIES})
    print(f"wrote {out}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    asyncio.run(_measure(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

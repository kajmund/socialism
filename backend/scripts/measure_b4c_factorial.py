"""B4c: factorial candidate generation (det/hybrid) x ranking (current/metadata).

Four live arms, two repetitions, timing split into embedding, generation,
prioritisation and Jev execution. No production change.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, replace
from pathlib import Path

from app.jev.system import HttpJevSystemOne
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
from app.services.research.sufficiency_experiment.gap_cases import (
    candidate_miss_synonyms,
    synonym_contradiction_notice,
    synonym_contradiction_semester,
)
from app.services.research.sufficiency_experiment.golden import (
    conflict_benchmark_cases,
    scripted_benchmark_cases,
    tail_claim_contradiction,
)
from app.services.research.sufficiency_experiment.loop import SufficiencyLoop
from app.services.research.sufficiency_experiment.types import ExperimentConfig

DEFAULT_OUT = Path("tests/integration/baselines/b4c-factorial-v1.json")
GOLD = Path("tests/integration/baselines/pair-gold-v1.json")
CASES = tuple(scripted_benchmark_cases()) + tuple(conflict_benchmark_cases()) + (
    tail_claim_contradiction(),
    candidate_miss_synonyms(),
    synonym_contradiction_semester(),
    synonym_contradiction_notice(),
)
COMPATIBLE = {"compatible_periods", "compatible_entities", "unknown_counterpart"}
ARM_SPEC = {
    "A": ("deterministic", "current"),
    "B": ("hybrid", "current"),
    "C": ("deterministic", "metadata"),
    "D": ("hybrid", "metadata"),
}
CONFIG = {
    arm: replace(
        ExperimentConfig(),
        route_authority=True,
        legacy_duplicate_resolution=False,
        pair_judgement=True,
        pair_strategy=strategy,
        pair_ordering=ordering,
    )
    for arm, (strategy, ordering) in ARM_SPEC.items()
}


class CountingEmbedding:
    provider_id = "openai"
    model: str
    dimension: int

    def __init__(self) -> None:
        self._inner = OpenAIEmbeddingProvider.from_settings()
        self.model = self._inner.model
        self.dimension = self._inner.dimension
        self.calls = 0
        self.texts = 0

    async def embed(self, texts):
        self.calls += 1
        self.texts += len(texts)
        return await self._inner.embed(texts)


def _key(left: str, right: str) -> frozenset[str]:
    return frozenset((left, right))


def _gold_facit() -> dict[str, dict[str, set[frozenset[str]]]]:
    out = {}
    for entry in json.loads(GOLD.read_text(encoding="utf-8"))["cases"]:
        out[entry["case_id"]] = {
            "contradiction": {_key(*pair) for pair in entry["contradiction_pairs"]},
            "compatible": {_key(*pair) for pair in entry["candidate_pairs"]}
            if not entry["contradiction_pairs"]
            else set(),
        }
    return out


def _marker_facit(case, report) -> dict[str, set[frozenset[str]]]:
    claims = list(report.claims)
    markers = {
        "late_evidence": ("Högsta domstolen tillämpar", "MOTBEVIS"),
        "candidate_miss_synonyms": ("Hundar", "Tamdjur"),
        "synonym_contradiction_semester": ("semesterdagar", "Semesterledigheten"),
        "synonym_contradiction_notice": ("månaders varsel", "Uppsägningstiden"),
    }
    out = {"contradiction": set(), "compatible": set()}
    if case.case_id not in markers:
        return out
    left_marker, right_marker = markers[case.case_id]
    left = next((claim for claim in claims if left_marker in claim.text), None)
    right = next((claim for claim in claims if right_marker in claim.text), None)
    if left and right:
        out["contradiction"] = {_key(left.claim_id, right.claim_id)}
    return out


async def _run_arm(arm: str, reps: int) -> dict:
    config = CONFIG[arm]
    client = HttpJevSystemOne()
    gold = _gold_facit()
    embedding = CountingEmbedding() if ARM_SPEC[arm][0] == "hybrid" else None
    rows = []
    unique_conflicts: set[str] = set()
    useful_facit: set[str] = set()
    for rep in range(reps):
        for case in CASES:
            loop = SufficiencyLoop(case.plan, case.evidence, client=client, config=config)
            if embedding is not None:
                loop.bind_embedding_provider(embedding)
            await loop.run()
            report = loop.report
            if report is None or report.pair_selection is None:
                continue
            selection = report.pair_selection
            base = gold.get(case.case_id, {"contradiction": set(), "compatible": set()})
            marker = _marker_facit(case, report)
            facit = {
                "contradiction": base["contradiction"] | marker["contradiction"],
                "compatible": base["compatible"] | marker["compatible"],
            }
            candidate_keys = {
                _key(pair.left_claim_id, pair.right_claim_id)
                for pair in selection.candidates
            }
            selected_keys = {
                _key(pair.left_claim_id, pair.right_claim_id)
                for pair in selection.selected
            }
            for conflict in (
                c for row in report.aggregations for c in row.conflicts if c.status == "unresolved"
            ):
                unique_conflicts.add(conflict.conflict_id)
            for key in selected_keys & facit["contradiction"]:
                useful_facit.add("|".join(sorted(key)))
            jev_ms = sum(item.scores.latency_ms for item in report.evaluations) + sum(
                item.latency_ms for item in report.pairs
            )
            rows.append(
                {
                    "arm": arm,
                    "rep": rep,
                    "case_id": case.case_id,
                    "draft": report.draft.result,
                    "expected": case.expected,
                    "correct": report.draft.result == case.expected,
                    "false_sufficient": report.draft.result == "sufficient" and case.expected == "insufficient",
                    "coverage_complete": bool(report.coverage_report and report.coverage_report.gate_complete),
                    "candidate_recall": bool(facit["contradiction"] & candidate_keys),
                    "recall_at_40": bool(facit["contradiction"] & selected_keys),
                    "candidates": len(selection.candidates),
                    "selected": len(selection.selected),
                    "jev_calls": report.jev_calls,
                    "total_ms": report.latency_ms,
                    "generation_ms": round(selection.latency_ms - selection.embedding_ms, 1),
                    "embedding_ms": round(selection.embedding_ms, 1),
                    "prioritization_ms": round(selection.prioritization_ms, 1),
                    "jev_ms": round(jev_ms, 1),
                }
            )
    totals = {
        "correct": sum(row["correct"] for row in rows),
        "false_sufficient": sum(row["false_sufficient"] for row in rows),
        "coverage_complete": sum(row["coverage_complete"] for row in rows),
        "candidate_recall": sum(row["candidate_recall"] for row in rows),
        "recall_at_40": sum(row["recall_at_40"] for row in rows),
        "unique_conflicts": len(unique_conflicts),
        "useful_facit_pairs": len(useful_facit),
        "jev_calls": sum(row["jev_calls"] for row in rows),
        "total_ms": round(sum(row["total_ms"] for row in rows), 1),
        "generation_ms": round(sum(row["generation_ms"] for row in rows), 1),
        "embedding_ms": round(sum(row["embedding_ms"] for row in rows), 1),
        "prioritization_ms": round(sum(row["prioritization_ms"] for row in rows), 1),
        "jev_ms": round(sum(row["jev_ms"] for row in rows), 1),
        "embedding_calls": embedding.calls if embedding else 0,
        "embedding_texts": embedding.texts if embedding else 0,
    }
    return {"config": asdict(config), "rows": rows, "totals": totals}


def _reference(arms: dict[str, dict]) -> str:
    ranked = sorted(
        arms,
        key=lambda arm: (
            -arms[arm]["totals"]["correct"],
            arms[arm]["totals"]["false_sufficient"],
            -arms[arm]["totals"]["recall_at_40"],
        ),
    )
    return ranked[0]


async def _run(out: Path, reps: int) -> dict:
    arms = {}
    for arm in ("A", "B", "C", "D"):
        arms[arm] = await _run_arm(arm, reps)
        print(arm, arms[arm]["totals"], flush=True)
    payload = {
        "measurement": "b4c_factorial",
        "note": "Deterministic/hybrid generation x current/metadata ordering, live Jev, two reps.",
        "reps": reps,
        "case_set": [case.case_id for case in CASES],
        "arms": arms,
        "recommended_reference": _reference(arms),
        "late_evidence": {
            arm: [
                {"rep": row["rep"], "draft": row["draft"], "candidate_recall": row["candidate_recall"], "recall_at_40": row["recall_at_40"]}
                for row in arms[arm]["rows"]
                if row["case_id"] == "late_evidence"
            ]
            for arm in arms
        },
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({arm: arms[arm]["totals"] for arm in arms}, indent=2))
    print("recommended_reference", payload["recommended_reference"])
    print(f"wrote {out}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--reps", type=int, default=2)
    args = parser.parse_args()
    asyncio.run(_run(args.out, args.reps))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

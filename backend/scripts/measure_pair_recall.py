"""Measure pair recall for the three A3 candidate strategies.

Deterministic runs offline. Embedding and hybrid runs require an embedding
provider and report their embedding calls separately. No Jev call is made:
this measures whether the right pairs are proposed, not whether Jev judges
them correctly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
from app.services.research.sufficiency_experiment.claims import (
    extract_claim_candidates,
)
from app.services.research.sufficiency_experiment.golden import all_golden_cases
from app.services.research.sufficiency_experiment.pairs import select_pairs
from app.services.research.sufficiency_experiment.segment import segment_evidence
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    PairSelection,
)

DEFAULT_GOLD = Path("tests/integration/baselines/pair-gold-v1.json")
DEFAULT_OUT = Path("tests/integration/baselines/pair-recall-v1.json")
STRATEGIES = ("deterministic", "embeddings", "hybrid")


def _claims(case, config):
    passages = segment_evidence(case.evidence, max_chars=config.max_passage_chars)
    return extract_claim_candidates(
        passages,
        {item.evidence_id: item for item in case.evidence},
        config=config,
    )[0]


def _facit(entry):
    pairs = [tuple(sorted(pair)) for pair in entry["candidate_pairs"]]
    return {"|".join(pair) for pair in pairs}


def _detail(selection: PairSelection, facit: set[str]) -> dict[str, object]:
    ranks = {
        pair.pair_id: index + 1
        for index, pair in enumerate(selection.candidates)
    }
    selected = {pair.pair_id for pair in selection.selected}
    before = [pair_id for pair_id in facit if pair_id in ranks]
    after = [pair_id for pair_id in facit if pair_id in selected]
    return {
        "input_claims": selection.input_claims,
        "candidate_pairs": len(selection.candidates),
        "selected_pairs": len(selection.selected),
        "omitted_by_budget": selection.omitted_by_budget,
        "recall_before_budget": len(before) / len(facit) if facit else None,
        "recall_at_budget": len(after) / len(facit) if facit else None,
        "facit": [
            {
                "pair_id": pair_id,
                "rank": ranks.get(pair_id),
                "selected": pair_id in selected,
                "sources": next(
                    (pair.sources for pair in selection.candidates if pair.pair_id == pair_id),
                    None,
                ),
            }
            for pair_id in sorted(facit)
        ],
        "latency_ms": round(selection.latency_ms, 3),
        "embedding_calls": selection.embedding_calls,
        "embedding_texts": selection.embedding_texts,
    }


async def _measure(gold: dict, config: ExperimentConfig, *, embeddings: bool):
    provider = OpenAIEmbeddingProvider.from_settings() if embeddings else None
    cases = {case.case_id: case for case in all_golden_cases()}
    results = []
    for entry in gold["cases"]:
        case = cases[entry["case_id"]]
        claims = _claims(case, config)
        facit = _facit(entry)
        strategies = {}
        for strategy in STRATEGIES:
            if strategy != "deterministic" and provider is None:
                strategies[strategy] = {"status": "unavailable"}
                continue
            selection = await select_pairs(
                claims,
                case.plan.needs,
                strategy=strategy,
                config=config,
                embedding_provider=provider,
            )
            strategies[strategy] = _detail(selection, facit)
        results.append(
            {
                "case_id": entry["case_id"],
                "negative_control": entry["negative_control"],
                "claims": len(claims),
                "strategies": strategies,
            }
        )
    return results


def _summary(results: list[dict]) -> dict[str, object]:
    positive = [row for row in results if not row["negative_control"]]
    summary: dict[str, object] = {}
    for strategy in STRATEGIES:
        rows = [
            row["strategies"][strategy]
            for row in positive
            if "recall_at_budget" in row["strategies"].get(strategy, {})
        ]
        summary[strategy] = {
            "cases": len(rows),
            "mean_recall_before_budget": _mean(rows, "recall_before_budget"),
            "mean_recall_at_budget": _mean(rows, "recall_at_budget"),
            "selected_pairs": sum(row["selected_pairs"] for row in rows),
            "embedding_calls": sum(row["embedding_calls"] for row in rows),
        }
    return summary


def _mean(rows: list[dict], key: str) -> float | None:
    if not rows:
        return None
    return sum(float(row[key]) for row in rows) / len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--embeddings", action="store_true")
    args = parser.parse_args()
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    config = ExperimentConfig()
    results = asyncio.run(_measure(gold, config, embeddings=args.embeddings))
    payload = {
        "measurement": "pair_recall",
        "note": (
            "Candidate generation only; no Jev calls. Embedding strategies "
            "report their embedding calls separately."
        ),
        "gold": str(args.gold),
        "embedding_model": (
            OpenAIEmbeddingProvider.from_settings().model if args.embeddings else None
        ),
        "config": {
            "max_pairs_per_need": config.max_pairs_per_need,
            "embedding_neighbors": config.embedding_neighbors,
            "max_claims_per_need": config.max_claims_per_need,
        },
        "summary": _summary(results),
        "cases": results,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

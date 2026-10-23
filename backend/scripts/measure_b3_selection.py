"""B3: Recall@Budget for pair prioritisation. Selection only; no Jev call.

Arms: current order (A), deterministic metadata priority (B), and metadata plus
existing embeddings (C). These are prioritisation strategies only; the A3
decision contract and the Jev verdicts are unchanged.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
from app.services.research.sufficiency_experiment.claims import extract_claim_candidates
from app.services.research.sufficiency_experiment.golden import all_golden_cases
from app.services.research.sufficiency_experiment.pairs import select_pairs
from app.services.research.sufficiency_experiment.prioritization import prioritize_pairs
from app.services.research.sufficiency_experiment.segment import segment_evidence
from app.services.research.sufficiency_experiment.types import ExperimentConfig

DEFAULT_OUT = Path("tests/integration/baselines/b3-selection-v1.json")
GOLD = Path("tests/integration/baselines/pair-gold-v1.json")
BUDGETS = (1, 5, 10, 20, 40)
ARMS = ("current", "metadata", "embedding")


def _claims(case, config):
    passages = segment_evidence(case.evidence, max_chars=config.max_passage_chars)
    claims, _ = extract_claim_candidates(
        passages, {item.evidence_id: item for item in case.evidence}, config=config
    )
    return claims, {claim.claim_id: claim for claim in claims}


def _pair_key(pair) -> frozenset[str]:
    return frozenset((pair.left_claim_id, pair.right_claim_id))


def _facit_keys(pairs) -> set[frozenset[str]]:
    return {frozenset(item) for item in pairs}


async def _measure(out: Path) -> dict:
    config = ExperimentConfig()
    gold = json.loads(GOLD.read_text(encoding="utf-8"))["cases"]
    cases = {case.case_id: case for case in all_golden_cases()}
    provider = OpenAIEmbeddingProvider.from_settings() if "embedding" in ARMS else None
    rows = []
    for entry in gold:
        case = cases[entry["case_id"]]
        claims, claims_by_id = _claims(case, config)
        selection = await select_pairs(
            claims,
            case.plan.needs,
            strategy="deterministic",
            config=config,
        )
        candidates = selection.candidates
        facit = _facit_keys(entry["contradiction_pairs"])
        control = _facit_keys(entry.get("candidate_pairs", [])) - facit
        arm_rows = {}
        for arm in ARMS:
            ranked = await prioritize_pairs(
                candidates,
                claims_by_id,
                ordering=arm,
                embedding_provider=provider,
            )
            positions = {}
            for index, pair in enumerate(ranked, start=1):
                if _pair_key(pair) in facit:
                    positions[str(sorted(_pair_key(pair)))] = index
            ranks = list(positions.values())
            curve = {
                str(budget): (1.0 if ranks and min(ranks) <= budget else 0.0)
                for budget in BUDGETS
            }
            control_positions = [
                index
                for index, pair in enumerate(ranked, start=1)
                if _pair_key(pair) in control
            ]
            arm_rows[arm] = {
                "known_contradiction_ranks": positions,
                "recall_at": curve,
                "best_rank": min(ranks) if ranks else None,
                "budget_needed": next((b for b in BUDGETS if ranks and min(ranks) <= b), None),
                "negative_control_rank": min(control_positions) if control_positions else None,
                "candidates": len(ranked),
                "facit_available": bool(facit & {_pair_key(pair) for pair in ranked}),
            }
        rows.append(
            {
                "case_id": case.case_id,
                "facit_pairs": sorted(sorted(item) for item in facit),
                "arms": arm_rows,
            }
        )
    tested = [row for row in rows if row["facit_pairs"]]
    curve = {}
    for arm in ARMS:
        curve[arm] = {
            str(budget): round(
                sum(row["arms"][arm]["recall_at"][str(budget)] for row in tested)
                / len(tested),
                3,
            )
            for budget in BUDGETS
        }
    payload = {
        "measurement": "b3_pair_prioritisation",
        "note": "Recall@Budget is measured on known pair-gold contradictions. No Jev call; final decision quality and coverage are separate measurements.",
        "config": asdict(config),
        "arms": list(ARMS),
        "budgets": list(BUDGETS),
        "positive_cases": [row["case_id"] for row in tested],
        "recall_at_budget": curve,
        "embedding_model": provider.model if provider is not None else None,
        "rows": rows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(curve, indent=2))
    for row in rows:
        print(row["case_id"], {arm: row["arms"][arm]["best_rank"] for arm in ARMS})
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

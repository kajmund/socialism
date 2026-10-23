"""Scripted A0-vs-A1 comparison of the route-authority contract.

No live model call. This records what changes in the final verdict when the
route outcome starts to count. A0 keeps the old emit-status path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, replace
from pathlib import Path

from app.jev.system import JevSystemOneResult, JevUsage
from app.services.research.evidence_screen import EVIDENCE_SCREEN_QUESTIONS
from app.services.research.fast_controller import ASSESSMENT_QUESTIONS
from app.services.research.sufficiency_experiment.assessor import run_experiment
from app.services.research.sufficiency_experiment.golden import short_sufficient
from app.services.research.sufficiency_experiment.types import ExperimentConfig

DEFAULT_OUT = Path("tests/integration/baselines/sufficiency-a1-route-authority-v1.json")


class RouteClient:
    def __init__(self, *, answerable: float, gap: float) -> None:
        self.answerable = answerable
        self.gap = gap

    async def ask(self, *, state, questions, model, timeout_seconds):
        if set(questions) == set(EVIDENCE_SCREEN_QUESTIONS):
            answers = {
                "relevant_to_question": _noul(0.95),
                "directly_supports_answer": _noul(0.95),
                "contradicts_current_evidence": _noul(0.05),
                "material_new_information": _noul(0.5),
                "likely_duplicate_or_redundant": _noul(0.05),
                "primary_or_high_authority_for_question": _noul(0.5),
            }
        elif set(questions) == set(ASSESSMENT_QUESTIONS):
            answers = {
                "answerable_now": _noul(self.answerable),
                "material_gap": _noul(self.gap),
                "contradiction": _noul(0.05),
                "follow_up_change": _noul(0.05),
                "additional_source": _noul(0.05),
            }
        else:
            raise AssertionError("unexpected question set")
        return JevSystemOneResult(
            answers=answers,
            model="scripted-a1",
            latency_ms=0.0,
            input_chars=0,
            usage=JevUsage(),
            raw={},
        )


def _noul(value: float) -> dict[str, float]:
    return {"noul": value}


def _config(route_authority: bool) -> ExperimentConfig:
    return replace(
        ExperimentConfig(
            route_authority=route_authority,
            legacy_duplicate_resolution=True,
            pair_judgement=False,
        )
    )


SCENARIOS = (
    ("route_uncertain", 0.85, 0.05),
    ("route_insufficient", 0.05, 0.95),
    ("route_sufficient", 0.95, 0.05),
)


async def run(out: Path) -> int:
    case = short_sufficient()
    rows = []
    for name, answerable, gap in SCENARIOS:
        for arm, enabled in (("A0", False), ("A1", True)):
            report = await run_experiment(
                case.plan,
                case.evidence,
                client=RouteClient(answerable=answerable, gap=gap),
                config=_config(enabled),
            )
            route = report.route
            rows.append(
                {
                    "scenario": name,
                    "arm": arm,
                    "route_answers": {
                        "answerable_now": answerable,
                        "material_gap": gap,
                    },
                    "draft": report.draft.result,
                    "status": report.status,
                    "route_choice": route.choice if route else None,
                    "final_outcome": route.final_outcome if route else None,
                    "route_valid": route.valid if route else None,
                    "rejection": route.rejection if route else None,
                }
            )
    payload = {
        "measurement": "scripted_a0_vs_a1",
        "note": "Scripted route answers, no live model; measures the A1 authority change only.",
        "config": {
            "A0": asdict(_config(False)),
            "A1": asdict(_config(True)),
        },
        "rows": rows,
    }
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for row in rows:
        print(
            row["scenario"],
            row["arm"],
            row["draft"],
            row["status"],
            row["route_choice"],
            row["final_outcome"],
        )
    print(f"wrote {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    return asyncio.run(run(args.out))


if __name__ == "__main__":
    raise SystemExit(main())

"""Offline benchmark: workflow experiment vs PR #420 budgeted Cerebras baseline."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict

# Offline harness never calls these services; Settings still requires the keys.
os.environ.setdefault("CEREBRAS_API_KEY", "offline-benchmark-not-used")
os.environ.setdefault("DEEPSEEK_API_KEY", "offline-benchmark-not-used")
os.environ.setdefault("OPENAI_API_KEY", "offline-benchmark-not-used")
os.environ.setdefault("SUPABASE_URL", "https://offline.invalid")
os.environ.setdefault("LOCAL_AUTH_JWT_SECRET", "offline-benchmark-not-used")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "offline-benchmark-not-used")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.services.research.sufficiency_experiment.benchmark import run_benchmark
from app.services.research.sufficiency_experiment.golden import all_golden_cases
from app.services.research.sufficiency_experiment.scripted import ScriptedSufficiencyJev


def main() -> int:
    report = asyncio.run(run_benchmark(all_golden_cases(), client=ScriptedSufficiencyJev()))
    payload = {
        "summary": report.summary(),
        "cases": [
            {
                "case_id": case.case_id,
                "expected": case.expected,
                "baseline": asdict(case.baseline),
                "experiment": asdict(case.experiment),
            }
            for case in report.cases
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

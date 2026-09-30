"""Explicit local replay artifacts, bound to the question and previous stage output."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pydantic import TypeAdapter

from app.services.research.assessment import ResearchAssessmentDraft
from app.services.research.followup import RuntimeResearchNeed
from app.services.research.models import ResearchEvidence

EVIDENCE = TypeAdapter(list[ResearchEvidence])
ASSESSMENT = TypeAdapter(ResearchAssessmentDraft)
GAPS = TypeAdapter(list[RuntimeResearchNeed])


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def save(path: Path, *, target: dict, stage: int, payload: object, parent: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "format": 1,
        "target_digest": digest(target),
        "stage": stage,
        "payload": payload,
        "parent_digest": parent,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read(path: Path, *, target: dict, stage: int, parent: str = "") -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        data["format"] != 1
        or data["target_digest"] != digest(target)
        or data["stage"] != stage
        or data["parent_digest"] != parent
    ):
        raise ValueError(
            "Replay does not match this question/context or previous stage; rerun its producer"
        )
    return data


class TimedStep:
    def __init__(self, stage: int, measurements: list[dict]) -> None:
        self.stage = stage
        self.measurements = measurements
        self.parts: dict[str, float] = {}

    def __enter__(self):
        self.started = perf_counter()
        return self

    def __exit__(self, error_type, _error, _traceback):
        self.measurements.append(
            {
                "stage": self.stage,
                "seconds": perf_counter() - self.started,
                "parts": self.parts,
                "status": "error" if error_type else "executed",
                "error_type": error_type.__name__ if error_type else None,
            }
        )


def summary(measurements: list[dict]) -> list[dict]:
    from math import ceil
    from statistics import median

    output = []
    for stage in sorted({row["stage"] for row in measurements}):
        rows = [row for row in measurements if row["stage"] == stage]
        times = sorted(row["seconds"] for row in rows)
        output.append(
            {
                "stage": stage,
                "runs": len(rows),
                "median_seconds": median(times),
                "p95_seconds": times[ceil(len(times) * 0.95) - 1],
                "errors": sum(row["status"] == "error" for row in rows),
                "contract_failures": sum(row["status"] == "contract_failed" for row in rows),
            }
        )
    return output

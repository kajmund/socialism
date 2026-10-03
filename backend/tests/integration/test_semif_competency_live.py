"""Live check: SemIf on CPU ranks the same competence contrast as the Jev gate.

Opt-in. Default pytest skips it, including CI. SemIf is a local scorer, not the
TypeSafe endpoint. Point it at a llama.cpp CPU build and a Qwen3.5-4B GGUF:

    RUN_SEMIF_INTEGRATION=1 \\
    SEMIF_SCORE=/tmp/SemIf/.venv/bin/semif-score \\
    SEMIF_GGUF=/path/to/Qwen_Qwen3.5-4B-Q4_K_M.gguf \\
    uv run pytest tests/integration/test_semif_competency_live.py
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.services.consult_competence import COMPETENCE_NOUL_THRESHOLD, _COMPETENCE

pytestmark = pytest.mark.integration

_ENV_FLAG = "RUN_SEMIF_INTEGRATION"
_MODEL = "Qwen/Qwen3.5-4B"
_REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
_QUESTION = (
    "Vilka svårigheter uppstår vid bedömning av kultur, IT och "
    "operativa integrationer vid ett företagsförvärv?"
)
_EXPERTS = (
    (
        "integration",
        "Integrationsriskbedömare. Bedömer kultur, IT och "
        "operativa integrationer vid företagsförvärv. "
        "Yrkesbakgrund: integrationsledare i förvärv.",
    ),
    (
        "straffratt",
        "Straffrättsjurist. Försvarar klienter i brottmål. "
        "Yrkesbakgrund: advokat med inriktning på straffrätt.",
    ),
)


def _opted_in() -> bool:
    return os.environ.get(_ENV_FLAG) == "1"


def _required_path(name: str) -> Path:
    raw = os.environ.get(name, "").strip()
    if not raw:
        pytest.skip(f"{name} is missing")
    path = Path(raw)
    if not path.is_file():
        pytest.skip(f"{name} does not point at a file: {path}")
    return path


def _decision_rows() -> list[dict[str, object]]:
    state = {
        "question": _QUESTION,
        "experts": [{"id": expert_id, "profile": profile} for expert_id, profile in _EXPERTS],
    }
    criteria = _COMPETENCE["criteria"]
    return [
        {
            "id": expert_id,
            "state": state,
            "question": f"{_COMPETENCE['instructions']} Expert {expert_id}.",
            "options": [
                {"id": "true", "description": criteria["true"]},
                {"id": "false", "description": criteria["false"]},
            ],
        }
        for expert_id, _profile in _EXPERTS
    ]


def _true_probability(row: dict[str, object]) -> float:
    option_ids = row["option_ids"]
    probabilities = row["probabilities"]
    if not isinstance(option_ids, list) or not isinstance(probabilities, list):
        raise AssertionError(f"SemIf row {row.get('id')} is missing option scores")
    if len(option_ids) != len(probabilities) or "true" not in option_ids:
        raise AssertionError(f"SemIf row {row.get('id')} has no true option")
    return float(probabilities[option_ids.index("true")])


def _score(score_bin: Path, gguf: Path, rows: list[dict[str, object]]) -> dict[str, float]:
    with tempfile.TemporaryDirectory(prefix="semif-competence-") as directory:
        root = Path(directory)
        source = root / "decisions.jsonl"
        output = root / "results.jsonl"
        source.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
        command = [
            str(score_bin),
            "--mode",
            "direct",
            "--backend",
            "llamacpp",
            "--gguf",
            str(gguf),
            "--model",
            os.environ.get("SEMIF_MODEL", _MODEL),
            "--revision",
            os.environ.get("SEMIF_REVISION", _REVISION),
            "--input",
            str(source),
            "--output",
            str(output),
        ]
        threads = os.environ.get("SEMIF_LLAMA_THREADS", "").strip()
        if threads:
            command.extend(["--llama-threads", threads])
        completed = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise AssertionError(f"semif-score failed ({completed.returncode}): {detail}")
        scored = [
            json.loads(line)
            for line in output.read_text().splitlines()
            if line.strip()
        ]
    return {str(row["id"]): _true_probability(row) for row in scored}


def test_semif_ranks_integration_competence_above_criminal_law() -> None:
    if not _opted_in():
        pytest.skip(f"set {_ENV_FLAG}=1 to score competence with local SemIf")
    scores = _score(_required_path("SEMIF_SCORE"), _required_path("SEMIF_GGUF"), _decision_rows())
    integration = scores["integration"]
    criminal = scores["straffratt"]
    assert integration >= COMPETENCE_NOUL_THRESHOLD, scores
    assert criminal < COMPETENCE_NOUL_THRESHOLD, scores
    assert integration > criminal, scores

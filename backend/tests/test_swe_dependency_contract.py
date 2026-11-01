"""Contract smoke for the independently versioned SWE dependency."""

from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
import tomllib

import pytest

pytest.importorskip("swe_native")

from swe.definition import compile_definition
from swe.runtime import run_workflow

pytestmark = pytest.mark.swe_runtime


async def test_pinned_swe_distribution_runs_a_workflow() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text())
    expected_tag = project["tool"]["uv"]["sources"]["swe-engine"]["tag"]
    direct_url = json.loads(
        importlib.metadata.distribution("swe-engine").read_text("direct_url.json")
    )
    assert direct_url["vcs_info"]["requested_revision"] == expected_tag

    definition = compile_definition(
        {
            "version": "1.0",
            "name": "dependency_contract",
            "entrypoint": "done",
            "limits": {"max_steps": 1, "max_depth": 1, "timeout_seconds": 5},
            "nodes": {"done": {"type": "end", "status": "completed"}},
        }
    )
    result = await run_workflow(definition, {}, {})

    assert result.status == "completed"
    assert Path(importlib.metadata.distribution("swe-engine").locate_file("swe")).is_dir()

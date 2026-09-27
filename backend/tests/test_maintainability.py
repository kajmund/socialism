"""The maintainability gate rejects new size and allows pinned debt to shrink."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# scripts/ is not a package. Load the gate by path so the test can call it.
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_maintainability.py"
_SPEC = importlib.util.spec_from_file_location("check_maintainability", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
check_maintainability = importlib.util.module_from_spec(_SPEC)
sys.modules["check_maintainability"] = check_maintainability
_SPEC.loader.exec_module(check_maintainability)

Limits = check_maintainability.Limits

LIMITS = Limits(
    max_file_lines=800,
    max_locals=15,
    max_statements=50,
    max_branches=12,
    max_complexity=10,
)


def _failures(**overrides: object) -> list[str]:
    arguments = {
        "file_lines": {},
        "functions": {},
        "baseline_files": {},
        "baseline_functions": {},
        "limits": LIMITS,
    }
    arguments.update(overrides)
    return check_maintainability.gate_failures(**arguments)


def test_new_module_over_the_line_limit_fails():
    assert _failures(file_lines={"app/new.py": 801}) == [
        "app/new.py: 801 lines exceeds limit 800"
    ]
    assert _failures(file_lines={"app/new.py": 800}) == []


def test_pinned_module_may_shrink_but_not_grow():
    assert _failures(file_lines={"app/old.py": 900}, baseline_files={"app/old.py": 1000}) == []
    assert _failures(file_lines={"app/old.py": 1001}, baseline_files={"app/old.py": 1000}) == [
        "app/old.py: 1001 lines exceeds pinned 1000 (limit 800)"
    ]


def test_new_function_over_the_local_limit_fails():
    assert _failures(functions={"app/new.py:build": {"locals": 16}}) == [
        "app/new.py:build: locals 16 exceeds limit 15"
    ]


def test_pinned_function_may_not_gain_locals():
    pinned = {"app/old.py:build": {"locals": 68}}
    shrunk = _failures(
        functions={"app/old.py:build": {"locals": 40}},
        baseline_functions=pinned,
    )
    assert shrunk == []
    assert _failures(functions={"app/old.py:build": {"locals": 69}}, baseline_functions=pinned) == [
        "app/old.py:build: locals 69 exceeds pinned 68 (limit 15)"
    ]


def test_repository_matches_maintainability_baseline():
    assert check_maintainability.main([]) == 0

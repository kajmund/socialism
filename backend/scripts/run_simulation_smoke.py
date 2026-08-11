"""Run the manual OASIS simulation smoke test.

Usage (from backend/):
  uv sync --extra oasis
  # DEEPSEEK_API_KEY must be a real key in backend/.env or the environment
  uv run python scripts/run_simulation_smoke.py
"""

from __future__ import annotations

import sys

import pytest


def main() -> int:
    return pytest.main(["-m", "smoke", "-v", "tests/smoke/test_oasis_simulation_smoke.py"])


if __name__ == "__main__":
    raise SystemExit(main())

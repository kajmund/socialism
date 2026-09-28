"""Budgets for module length and # noqa must fail closed."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _load_checker():
    path = BACKEND / "scripts" / "check_maintainability.py"
    spec = importlib.util.spec_from_file_location("check_maintainability", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CHECKER = _load_checker()


def _config(*, modules: dict[str, int] | None = None, noqas: dict[str, int] | None = None):
    return CHECKER.MaintainabilityConfig(
        app_max_lines=500,
        tests_max_lines=1000,
        module_baseline=modules or {},
        noqa_baseline=noqas or {},
    )


def _file(
    path: str,
    *,
    lines: int,
    noqa: dict[str, int] | None = None,
    file_noqa: bool = False,
):
    return CHECKER.FileStats(
        path=path,
        lines=lines,
        noqa=noqa or {},
        file_noqa=file_noqa,
    )


def test_new_module_over_limit_fails():
    errors = CHECKER.evaluate(
        files=[_file("app/services/new_thing.py", lines=501)],
        config=_config(),
    )
    assert any("no module-baseline" in item for item in errors)


def test_new_plr0913_noqa_fails():
    errors = CHECKER.evaluate(
        files=[_file("app/services/small.py", lines=40, noqa={"PLR0913": 1})],
        config=_config(),
    )
    assert any("new # noqa: PLR0913" in item for item in errors)


def test_file_level_ruff_noqa_fails():
    errors = CHECKER.evaluate(
        files=[_file("app/services/small.py", lines=10, file_noqa=True)],
        config=_config(),
    )
    assert any("file-level" in item for item in errors)


def test_baselined_module_must_not_grow():
    errors = CHECKER.evaluate(
        files=[_file("app/services/prompt_catalog.py", lines=3721)],
        config=_config(modules={"app/services/prompt_catalog.py": 3720}),
    )
    assert any("grew from 3720" in item for item in errors)


def test_update_only_lowers_baselines():
    files = [
        _file("app/big.py", lines=510, noqa={"C901": 1}),
        _file("app/gone.py", lines=20),
    ]
    config = _config(
        modules={"app/big.py": 600, "app/gone.py": 520, "app/missing.py": 800},
        noqas={"app/big.py:C901": 3, "app/gone.py:PLR0913": 1},
    )
    modules, noqas = CHECKER.lowered_baselines(files=files, config=config)
    assert modules == {"app/big.py": 510}
    assert noqas == {"app/big.py:C901": 1}


def test_current_tree_passes():
    config = CHECKER.load_config(BACKEND / "pyproject.toml")
    files = CHECKER.scan_tree(BACKEND)
    assert CHECKER.evaluate(files=files, config=config) == []


def test_ruff_rejects_eight_argument_function(tmp_path: Path):
    target = tmp_path / "too_many_args.py"
    target.write_text("def crowded(a, b, c, d, e, f, g, h):\n    return a\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            str(target),
            "--config",
            str(BACKEND / "pyproject.toml"),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=BACKEND,
    )
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "too-many-arguments" in output
    assert "8 > 7" in output

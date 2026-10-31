"""Fail when the engine package grows a dependency on the application.

`backend/app/swe` is the engine: it may import only its own modules, the
standard library and declared engine dependencies. Anything from `app.config`,
`app.jev` or `app.services` is a domain import and breaks the boundary the
extraction depends on (see ``docs/swe-standalone/10-pr1-b1-python-boundary.md``).

Application code may keep importing ``app.swe``; that direction is correct.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1] / "app" / "swe"

DOMAIN_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+app\.(config|jev|services)\b",
    re.MULTILINE,
)

#: Names that belong to a domain and must never be exported by the engine.
FORBIDDEN_EXPORTS = frozenset(
    {"FEATURE_IDS", "WorkflowHostContext", "workflow_catalog_dir"}
)


def _modules() -> list[Path]:
    return sorted(ENGINE_DIR.glob("*.py"))


def test_engine_package_has_no_domain_imports() -> None:
    offenders = [
        f"{path.name}:{line_no}"
        for path in _modules()
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        )
        if DOMAIN_IMPORT.match(line)
    ]
    assert offenders == [], (
        "app/swe must not import the application; move the caller instead: "
        f"{offenders}"
    )


def test_engine_package_has_no_prompt_catalog_dependency() -> None:
    offenders = [
        path.name
        for path in _modules()
        if "prompt_catalog" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        "the prompt catalog is host configuration and is injected, not imported: "
        f"{offenders}"
    )


def test_engine_public_api_excludes_host_concepts() -> None:
    import app.swe

    leaked = sorted(FORBIDDEN_EXPORTS.intersection(app.swe.__all__))
    assert leaked == [], f"host concepts exported by the engine: {leaked}"


def test_engine_imports_without_application_state() -> None:
    """Importing the engine must not require config, JEV or a database."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.swe, app.swe.runtime_dispatch; "
            "print('ok')",
        ],
        capture_output=True,
        text=True,
        cwd=str(ENGINE_DIR.parents[1]),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


@pytest.mark.parametrize("forbidden", sorted(FORBIDDEN_EXPORTS))
def test_host_concepts_are_owned_by_the_application(forbidden: str) -> None:
    from app.services import swe_host

    assert hasattr(swe_host, forbidden) or forbidden == "FEATURE_IDS"

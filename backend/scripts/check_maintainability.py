"""Fail when backend modules or functions get harder to maintain.

Existing debt is pinned in maintainability_baseline.json. A file or function
already over its limit may stay there or shrink. New code has to fit.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "maintainability_baseline.json"
SCAN_ROOTS = ("app", "tests")
RULES = {
    "PLR0912": "branches",
    "PLR0914": "locals",
    "PLR0915": "statements",
    "C901": "complexity",
}
COUNT = re.compile(r"\((\d+) > (\d+)\)")


@dataclass(frozen=True)
class Limits:
    max_file_lines: int
    max_locals: int
    max_statements: int
    max_branches: int
    max_complexity: int

    def for_metric(self, metric: str) -> int:
        return {
            "locals": self.max_locals,
            "statements": self.max_statements,
            "branches": self.max_branches,
            "complexity": self.max_complexity,
        }[metric]


def load_limits(pyproject: Path) -> Limits:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    maintainability = data["tool"]["maintainability"]
    pylint = data["tool"]["ruff"]["lint"]["pylint"]
    mccabe = data["tool"]["ruff"]["lint"]["mccabe"]
    return Limits(
        max_file_lines=maintainability["max-file-lines"],
        max_locals=pylint["max-locals"],
        max_statements=pylint["max-statements"],
        max_branches=pylint["max-branches"],
        max_complexity=mccabe["max-complexity"],
    )


def module_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for folder in SCAN_ROOTS:
        for path in sorted((root / folder).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            paths.append(path)
    return paths


def index_functions(tree: ast.AST) -> dict[int, str]:
    found: dict[int, str] = {}

    class Index(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._function(node)

        def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            self.stack.append(node.name)
            found[node.lineno] = ".".join(self.stack)
            self.generic_visit(node)
            self.stack.pop()

    Index().visit(tree)
    counts = Counter(found.values())
    if any(count > 1 for count in counts.values()):
        return {
            line: f"{name}@{line}" if counts[name] > 1 else name
            for line, name in found.items()
        }
    return found


def read_module(path: Path) -> tuple[int, dict[int, str]]:
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as error:
        raise SystemExit(f"{path} does not parse: {error}") from error
    return len(text.splitlines()), index_functions(tree)


def ruff_diagnostics(root: Path) -> list[dict[str, object]]:
    ruff = Path(sys.executable).with_name("ruff")
    if not ruff.is_file():
        raise SystemExit(f"ruff is not installed next to {sys.executable}")
    completed = subprocess.run(
        [
            str(ruff),
            "check",
            *SCAN_ROOTS,
            "--preview",
            "--select",
            "PLR0912,PLR0914,PLR0915,C901",
            "--output-format",
            "json",
            "--exit-zero",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr or completed.stdout)
    payload = json.loads(completed.stdout)
    if not isinstance(payload, list):
        raise SystemExit("ruff did not return a JSON list")
    return payload


def measure(root: Path) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    file_lines: dict[str, int] = {}
    functions_at: dict[str, dict[int, str]] = {}
    for path in module_paths(root):
        relative = path.relative_to(root).as_posix()
        lines, indexed = read_module(path)
        file_lines[relative] = lines
        functions_at[relative] = indexed

    functions: dict[str, dict[str, int]] = {}
    for item in ruff_diagnostics(root):
        code = item["code"]
        if not isinstance(code, str) or code not in RULES:
            continue
        filename = item["filename"]
        message = item["message"]
        location = item["location"]
        if (
            not isinstance(filename, str)
            or not isinstance(message, str)
            or not isinstance(location, dict)
        ):
            raise SystemExit(f"unexpected ruff diagnostic: {item}")
        row = location["row"]
        if not isinstance(row, int):
            raise SystemExit(f"unexpected ruff location: {item}")
        matched = COUNT.search(message)
        if matched is None:
            raise SystemExit(f"unrecognized ruff message: {message}")
        path = Path(filename)
        if path.is_absolute():
            relative = path.resolve().relative_to(root).as_posix()
        else:
            relative = path.as_posix()
        name = functions_at[relative].get(row)
        if name is None:
            raise SystemExit(f"ruff reported {code} at {relative}:{row}, which is not a function")
        key = f"{relative}:{name}"
        functions.setdefault(key, {})[RULES[code]] = int(matched.group(1))
    return file_lines, functions


def gate_failures(
    *,
    file_lines: dict[str, int],
    functions: dict[str, dict[str, int]],
    baseline_files: dict[str, int],
    baseline_functions: dict[str, dict[str, int]],
    limits: Limits,
) -> list[str]:
    failures: list[str] = []
    for path, lines in sorted(file_lines.items()):
        if lines <= limits.max_file_lines:
            continue
        pinned = baseline_files.get(path)
        if pinned is None:
            failures.append(f"{path}: {lines} lines exceeds limit {limits.max_file_lines}")
        elif lines > pinned:
            failures.append(
                f"{path}: {lines} lines exceeds pinned {pinned} (limit {limits.max_file_lines})"
            )
    for key, metrics in sorted(functions.items()):
        pinned = baseline_functions.get(key, {})
        for metric, value in sorted(metrics.items()):
            limit = limits.for_metric(metric)
            allowed = pinned.get(metric)
            if allowed is None:
                failures.append(f"{key}: {metric} {value} exceeds limit {limit}")
            elif value > allowed:
                failures.append(f"{key}: {metric} {value} exceeds pinned {allowed} (limit {limit})")
    return failures


def load_baseline(path: Path) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    files = data.get("files")
    functions = data.get("functions")
    if not isinstance(files, dict) or not isinstance(functions, dict):
        raise SystemExit(f"{path} must contain files and functions objects")
    return files, functions


def write_baseline(
    path: Path,
    *,
    file_lines: dict[str, int],
    functions: dict[str, dict[str, int]],
    limits: Limits,
) -> None:
    payload = {
        "note": (
            "Pinned sizes for code that already exceeds the maintainability limits. "
            "Entries may shrink. Do not add a key or raise a number to let new code through."
        ),
        "files": {
            name: lines
            for name, lines in sorted(file_lines.items())
            if lines > limits.max_file_lines
        },
        "functions": {
            key: {metric: value for metric, value in sorted(metrics.items())}
            for key, metrics in sorted(functions.items())
        },
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Lower pinned sizes to the current tree. Refuses if that would add debt.",
    )
    args = parser.parse_args(argv)
    limits = load_limits(ROOT / "pyproject.toml")
    file_lines, functions = measure(ROOT)
    baseline_files, baseline_functions = load_baseline(BASELINE_PATH)
    failures = gate_failures(
        file_lines=file_lines,
        functions=functions,
        baseline_files=baseline_files,
        baseline_functions=baseline_functions,
        limits=limits,
    )
    if args.write_baseline:
        if failures:
            print("Baseline was not written.")
        else:
            write_baseline(
                BASELINE_PATH,
                file_lines=file_lines,
                functions=functions,
                limits=limits,
            )
            print(f"wrote {BASELINE_PATH}")
            return 0
    if not failures:
        return 0
    print("Maintainability check failed. Split the code so it fits.")
    print("Do not raise maintainability_baseline.json to admit the new size.")
    for failure in failures:
        print(failure)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

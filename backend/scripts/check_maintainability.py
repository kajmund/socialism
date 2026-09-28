"""Enforce module length and # noqa budgets. Ruff has no module-length rule."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

INLINE_NOQA = re.compile(
    r"#\s*noqa(?::\s*([A-Z][A-Z0-9]+(?:\s*,\s*[A-Z][A-Z0-9]+)*))?",
    re.IGNORECASE,
)
FILE_NOQA = re.compile(r"^#\s*ruff:\s*noqa\b", re.IGNORECASE)

DEFAULT_APP_MAX = 500
DEFAULT_TESTS_MAX = 1000
SECTION_MARKERS = (
    "[tool.socialism.maintainability]",
    "[tool.socialism.maintainability.module-baseline]",
    "[tool.socialism.maintainability.noqa-baseline]",
)


@dataclass(frozen=True)
class MaintainabilityConfig:
    app_max_lines: int
    tests_max_lines: int
    module_baseline: dict[str, int]
    noqa_baseline: dict[str, int]


@dataclass(frozen=True)
class FileStats:
    path: str
    lines: int
    noqa: dict[str, int]
    file_noqa: bool


def repo_root_from(script: Path) -> Path:
    return script.resolve().parent.parent


def load_config(pyproject: Path) -> MaintainabilityConfig:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    raw = data.get("tool", {}).get("socialism", {}).get("maintainability", {})
    modules = {str(path): int(lines) for path, lines in raw.get("module-baseline", {}).items()}
    noqas = {str(key): int(count) for key, count in raw.get("noqa-baseline", {}).items()}
    return MaintainabilityConfig(
        app_max_lines=int(raw.get("app-max-lines", DEFAULT_APP_MAX)),
        tests_max_lines=int(raw.get("tests-max-lines", DEFAULT_TESTS_MAX)),
        module_baseline=modules,
        noqa_baseline=noqas,
    )


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def parse_noqa_codes(codes: str | None) -> list[str]:
    if codes is None:
        return ["NOQA"]
    return [code.strip().upper() for code in codes.split(",") if code.strip()]


def comment_suffix(line: str) -> str | None:
    in_single = False
    in_double = False
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\" and (in_single or in_double):
            index += 2
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[index:]
        index += 1
    return None


def scan_file(path: Path, *, relative: str) -> FileStats:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    counts: Counter[str] = Counter()
    file_noqa = False
    for line in lines:
        comment = comment_suffix(line)
        if comment is None:
            continue
        if FILE_NOQA.match(comment):
            file_noqa = True
        match = INLINE_NOQA.search(comment)
        if match is None:
            continue
        for code in parse_noqa_codes(match.group(1)):
            counts[code] += 1
    return FileStats(path=relative, lines=len(lines), noqa=dict(counts), file_noqa=file_noqa)


def iter_python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def scan_tree(backend: Path) -> list[FileStats]:
    found: list[FileStats] = []
    for area in ("app", "tests"):
        base = backend / area
        if not base.is_dir():
            continue
        for path in iter_python_files(base):
            found.append(scan_file(path, relative=path.relative_to(backend).as_posix()))
    return found


def area_limit(relative: str, config: MaintainabilityConfig) -> int:
    if relative.startswith("tests/"):
        return config.tests_max_lines
    return config.app_max_lines


def noqa_key(relative: str, rule: str) -> str:
    return f"{relative}:{rule}"


def module_errors(item: FileStats, config: MaintainabilityConfig) -> list[str]:
    limit = area_limit(item.path, config)
    baseline = config.module_baseline.get(item.path)
    if item.lines > limit and baseline is None:
        return [f"{item.path}: {item.lines} lines exceeds {limit} and has no module-baseline"]
    if item.lines > limit and baseline is not None and item.lines > baseline:
        return [
            f"{item.path}: grew from {baseline} to {item.lines} lines "
            "(module-baseline may only decrease)"
        ]
    if item.lines > limit and baseline is not None and item.lines < baseline:
        return [
            f"{item.path}: shrank from {baseline} to {item.lines} lines; "
            "run check_maintainability.py --update"
        ]
    if item.lines <= limit and baseline is not None:
        return [
            f"{item.path}: now {item.lines} lines (limit {limit}); "
            "run check_maintainability.py --update to drop the module-baseline"
        ]
    return []


def noqa_errors(item: FileStats, config: MaintainabilityConfig) -> list[str]:
    errors: list[str] = []
    for rule, count in sorted(item.noqa.items()):
        allowed = config.noqa_baseline.get(noqa_key(item.path, rule))
        if allowed is None:
            errors.append(f"{item.path}: new # noqa: {rule} is not in noqa-baseline")
        elif count > allowed:
            errors.append(
                f"{item.path}: # noqa: {rule} grew from {allowed} to {count} "
                "(noqa-baseline may only decrease)"
            )
        elif count < allowed:
            errors.append(
                f"{item.path}: # noqa: {rule} shrank from {allowed} to {count}; "
                "run check_maintainability.py --update"
            )
    return errors


def stale_baseline_errors(files: list[FileStats], config: MaintainabilityConfig) -> list[str]:
    errors: list[str] = []
    seen_noqa = {noqa_key(item.path, rule) for item in files for rule in item.noqa}
    present = {item.path for item in files}
    for key, allowed in sorted(config.noqa_baseline.items()):
        if key not in seen_noqa and allowed > 0:
            errors.append(f"{key}: noqa-baseline {allowed} is stale; run --update")
    for path, baseline in sorted(config.module_baseline.items()):
        if path not in present:
            errors.append(
                f"{path}: module-baseline {baseline} points at a missing file; run --update"
            )
    return errors


def evaluate(*, files: list[FileStats], config: MaintainabilityConfig) -> list[str]:
    errors: list[str] = []
    for item in files:
        if item.file_noqa:
            errors.append(f"{item.path}: file-level '# ruff: noqa' is forbidden")
        errors.extend(module_errors(item, config))
        errors.extend(noqa_errors(item, config))
    errors.extend(stale_baseline_errors(files, config))
    return errors


def lowered_baselines(
    *,
    files: list[FileStats],
    config: MaintainabilityConfig,
) -> tuple[dict[str, int], dict[str, int]]:
    modules = dict(config.module_baseline)
    noqas = dict(config.noqa_baseline)
    present = {item.path for item in files}
    for path in list(modules):
        if path not in present:
            del modules[path]
    for item in files:
        limit = area_limit(item.path, config)
        if item.path in modules:
            if item.lines <= limit:
                del modules[item.path]
            elif item.lines < modules[item.path]:
                modules[item.path] = item.lines
        for rule, count in item.noqa.items():
            key = noqa_key(item.path, rule)
            if key in noqas and count < noqas[key]:
                noqas[key] = count
    for key in list(noqas):
        if noqas[key] <= 0:
            del noqas[key]
            continue
        path, _sep, rule = key.partition(":")
        match = next((item for item in files if item.path == path), None)
        if match is None or match.noqa.get(rule, 0) == 0:
            del noqas[key]
    return modules, noqas


def render_section(config: MaintainabilityConfig) -> str:
    lines = [
        "[tool.socialism.maintainability]",
        f"app-max-lines = {config.app_max_lines}",
        f"tests-max-lines = {config.tests_max_lines}",
        "",
        "[tool.socialism.maintainability.module-baseline]",
    ]
    for path, count in sorted(config.module_baseline.items()):
        lines.append(f'"{path}" = {count}')
    lines.extend(["", "[tool.socialism.maintainability.noqa-baseline]"])
    for key, count in sorted(config.noqa_baseline.items()):
        lines.append(f'"{key}" = {count}')
    return "\n".join(lines) + "\n"


def strip_section(text: str) -> str:
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped in SECTION_MARKERS:
            skipping = True
            continue
        if skipping and stripped.startswith("[") and stripped not in SECTION_MARKERS:
            skipping = False
        if not skipping:
            kept.append(line)
    return "".join(kept).rstrip() + "\n\n"


def write_config(pyproject: Path, config: MaintainabilityConfig) -> None:
    body = strip_section(pyproject.read_text(encoding="utf-8"))
    pyproject.write_text(body + render_section(config), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Lower module-baseline and noqa-baseline to match the current tree.",
    )
    parser.add_argument(
        "--backend",
        type=Path,
        default=None,
        help="Backend root (defaults to the directory that contains this script's parent).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    backend = args.backend.resolve() if args.backend else repo_root_from(Path(__file__))
    pyproject = backend / "pyproject.toml"
    config = load_config(pyproject)
    files = scan_tree(backend)
    if args.update:
        modules, noqas = lowered_baselines(files=files, config=config)
        write_config(
            pyproject,
            MaintainabilityConfig(
                app_max_lines=config.app_max_lines,
                tests_max_lines=config.tests_max_lines,
                module_baseline=modules,
                noqa_baseline=noqas,
            ),
        )
        print("Lowered maintainability baselines where the tree shrank.")
        config = load_config(pyproject)
    errors = evaluate(files=files, config=config)
    if errors:
        print("Maintainability check failed:", file=sys.stderr)
        for item in errors:
            print(f"  {item}", file=sys.stderr)
        return 1
    print(
        f"Maintainability check passed ({len(files)} modules, "
        f"{len(config.module_baseline)} baselined)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

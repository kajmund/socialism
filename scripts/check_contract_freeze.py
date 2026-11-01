#!/usr/bin/env python3
"""A changed contract needs a version bump for its *type*, not for being touched.

Two failure modes this gate must survive:

1. **Silent drift** — a journal field is renamed, the fixtures and manifest are
   regenerated, everything stays green, and every existing journal file is now
   misinterpreted.
2. **False alarms** — bumping `CONTRACT_VERSION` necessarily edits the file that
   also holds the journal codec, and regenerating a fixture changes example
   values. Neither may demand an unrelated journal schema bump.

So the gate works on **contract types** and compares **wire form**, not paths or
values:

    SWD form                      -> SWD_VERSION
    journal wire form             -> JOURNAL_SCHEMA_VERSION
    needs/evidence/operations API -> CONTRACT_VERSION

A type is "affected" when its wire form or public API signature changed. Only an
affected type needs its version bumped. A file touched without changing the form
(a comment, a test, a regenerated example value) does not.

Bootstrap: while `contracts/` does not exist at the base commit, the initial
freeze may start at version 1 with a documented decision. The exception is
self-closing — once contracts exist at the base it can never apply again.

Usage:
    python3 scripts/check_contract_freeze.py --base <sha> --head <sha>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Overridable so the mutation matrix can point the gate at a throwaway repo.
ROOT = Path(os.environ.get("CONTRACT_FREEZE_ROOT") or Path(__file__).resolve().parent.parent)

DECISION_MARKERS = ("Kontraktsändring:", "Contract change:")
DECISION_DIR = "docs/swe-standalone/"
GUARD_SCRIPT = "scripts/check_contract_freeze.py"

SWD = "swd"
JOURNAL = "journal"
API = "contracts"

VERSIONS = {
    SWD: ("python/swe/schema.py", "SWD_VERSION"),
    JOURNAL: ("crates/swe-native/src/journal.rs", "JOURNAL_SCHEMA_VERSION"),
    API: ("crates/swe-reference/src/journal.rs", "CONTRACT_VERSION"),
}

FIXTURES = {
    SWD: ("contracts/swd-v1-workflow.json",),
    JOURNAL: ("contracts/journal-v1-events.json", "contracts/journal-v1-header.json"),
}

SOURCES = {
    SWD: ("crates/swe-native/src/definition.rs",),
    JOURNAL: ("crates/swe-native/src/journal.rs",),
    API: (
        "crates/swe-native/src/needs.rs",
        "crates/swe-native/src/evidence.rs",
        "crates/swe-native/src/operations.rs",
    ),
}

EXTRA_CONTRACT_PATHS = ("python/swe/swd_v1.schema.json",)

CONTRACT_PATHS = (
    "contracts/",
    GUARD_SCRIPT,
    *EXTRA_CONTRACT_PATHS,
    *[path for paths in FIXTURES.values() for path in paths],
    *[path for paths in SOURCES.values() for path in paths],
)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def path_exists_at(rev: str, path: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{rev}:{path}"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def read_at(rev: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{rev}:{path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def changed_paths(base: str, head: str) -> list[str]:
    merge_base = git("merge-base", base, head).strip()
    return [line for line in git("diff", "--name-only", merge_base, head).splitlines() if line]


def read_version(rev: str, path: str, name: str) -> str | None:
    blob = read_at(rev, path)
    if blob is None:
        return None
    match = re.search(
        rf"{name}\s*(?::\s*[A-Za-z0-9_]+\s*)?=\s*(\"[^\"]*\"|\d+(?:\.\d+)*)", blob
    )
    if not match:
        return None
    return match.group(1).strip('"')


def version_of(contract: str, rev: str) -> str | None:
    path, name = VERSIONS[contract]
    return read_version(rev, path, name)


def shape(value: object) -> object:
    """The wire form of a JSON value: keys and types, never scalar values.

    Values such as the definition hash, timestamps, amounts or the version number
    are examples, not form. Renaming a key, changing a type or adding an event
    variant changes the shape.
    """
    if isinstance(value, dict):
        return {key: shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        shapes = [shape(item) for item in value]
        return sorted({json.dumps(item, sort_keys=True) for item in shapes})
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    return type(value).__name__


def fixture_shape(rev: str, path: str) -> object | None:
    blob = read_at(rev, path)
    if blob is None:
        return None
    try:
        return shape(json.loads(blob))
    except json.JSONDecodeError:
        return None


DECLARATION = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const|static|fn|struct|enum|trait|type)\b"
)


def source_shape(rev: str, path: str) -> object | None:
    """The declared API/wire surface of a Rust file, ignoring bodies and comments.

    Only declaration lines are compared, whitespace-normalised. A comment, a test
    body or a private implementation detail therefore does not count as a
    contract change, while a renamed field, variant or signature does. Enum
    *variants* and struct *fields* matter for the journal wire form, so they are
    captured as normalised lines inside enum/struct bodies.
    """
    blob = read_at(rev, path)
    if blob is None:
        return None
    declarations: set[str] = set()
    in_enum = False
    depth = 0
    for line in blob.splitlines():
        stripped = line.strip()
        if stripped.startswith(("//", "#[", "*", "/*")):
            continue
        if DECLARATION.match(line):
            declarations.add(" ".join(stripped.split()))
            in_enum = re.match(r"^\s*pub(?:\([^)]*\))?\s+enum\b", line) is not None
            depth = 0
        if in_enum:
            depth += line.count("{") - line.count("}")
            if depth <= 0 and "{" in line:
                in_enum = False
            elif "{" in line or depth > 0:
                if stripped and not stripped.startswith(("{", "}", "#")):
                    declarations.add(" " + " ".join(stripped.split()))
    return sorted(declarations)


def contract_shape(contract: str, rev: str) -> dict[str, object]:
    parts: dict[str, object] = {}
    for path in FIXTURES.get(contract, ()):
        parts[path] = fixture_shape(rev, path)
    for path in EXTRA_CONTRACT_PATHS:
        if contract is SWD:
            parts[path] = fixture_shape(rev, path)
    for path in SOURCES.get(contract, ()):
        parts[path] = source_shape(rev, path)
    return parts


def affected_contracts(base: str, head: str) -> list[str]:
    return [
        contract
        for contract in VERSIONS
        if contract_shape(contract, base) != contract_shape(contract, head)
    ]


def documented_decision(base: str, head: str) -> bool:
    merge_base = git("merge-base", base, head).strip()
    for path in changed_paths(base, head):
        if not path.startswith(DECISION_DIR) or not path.endswith(".md"):
            continue
        diff = git("diff", "-U0", merge_base, head, "--", path)
        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                if any(marker in line for marker in DECISION_MARKERS):
                    return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()

    if not args.base:
        print("contract freeze: no base commit, skipping (not a pull request)")
        return 0

    # The gate itself may not be deleted: if it exists at the base it must still
    # exist at the head, whatever else changed.
    if path_exists_at(args.base, GUARD_SCRIPT) and not path_exists_at(args.head, GUARD_SCRIPT):
        print(
            "\ncontract freeze FAILED: the contract gate script was deleted. "
            f"Restore {GUARD_SCRIPT}; a gate that can be removed is not a gate.",
            file=sys.stderr,
        )
        return 1

    changed = changed_paths(args.base, args.head)
    contract_touched = [path for path in changed if path.startswith(CONTRACT_PATHS)]
    if not contract_touched:
        print("contract freeze: no contract path changed")
        return 0

    documented = documented_decision(args.base, args.head)
    affected = affected_contracts(args.base, args.head)
    bootstrap = not path_exists_at(args.base, "contracts/")

    print("contract freeze:")
    for path in contract_touched:
        print(f"  touched: {path}")
    print(f"  affected types: {affected or 'none (form unchanged)'}")
    print(f"  bootstrap (no contracts/ at base): {bootstrap}")
    print(f"  documented decision: {documented}")

    if not documented:
        print(
            "\ncontract freeze FAILED: a contract path changed without a documented "
            f"decision (a line containing one of {DECISION_MARKERS} in {DECISION_DIR}).",
            file=sys.stderr,
        )
        return 1

    failures: list[str] = []
    for contract in affected:
        before = version_of(contract, args.base)
        after = version_of(contract, args.head)
        if before is None or after is None:
            path, name = VERSIONS[contract]
            failures.append(f"{contract}: could not read {name} from {path}")
            continue
        if before == after:
            if bootstrap:
                print(
                    f"  {contract}: form changed but version stays {before} — allowed by "
                    "the bootstrap exception (contracts/ does not exist at the base)"
                )
            else:
                path, name = VERSIONS[contract]
                failures.append(
                    f"{contract}: wire form changed but its version stayed {before}; "
                    f"bump {name} in {path}"
                )
        else:
            print(f"  {contract}: version {before} -> {after}")

    if failures:
        print("\ncontract freeze FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("contract freeze OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

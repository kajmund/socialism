#!/usr/bin/env python3
"""The mutation gate: every critical mutation is classified, and drift blocks CI.

Why not "run cargo-mutants and require every mutant to die": a green mutation
number can lie (a tautological test passes every mutant), and some mutants are
genuinely equivalent or outside the contract. The owner's rule is therefore:

    every critical mutation is classified as detected, equivalent or excepted
    with a justification; new surviving mutations block CI.

This script executes a **verified baseline** of mutations instead of trusting a
number:

* ``detected``   — the mutation must make at least one test fail. If it stops
                   failing, the test that was supposed to catch it has rotted.
* ``equivalent`` — the mutation must keep the suite green because it cannot
                   change behaviour, and the justification says why.
* ``excepted``   — the mutation keeps the suite green and we accept that, with a
                   recorded justification for why the behaviour is not part of
                   the contract.

A mutation whose outcome disagrees with its classification fails the gate. So
does a mutation that cannot be applied: a text replacement that matches nothing
would otherwise "pass" by doing nothing, which is the failure mode this whole
programme keeps finding. Adding a new mutation without classifying it blocks CI
because the manifest is the only way in.

The manifest lives in ``mutations/baseline.json`` next to this script's root.
Run locally with ``python3 scripts/check_mutations.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "mutations" / "baseline.json"
CARGO = "cargo"
# Empty by default: a clean runner has no registry cache, so the first resolve
# needs the network. CI fetches the locked set explicitly and may pass --offline;
# a warm development machine can do the same.
CARGO_OFFLINE: list[str] = []


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if data.get("version") != 1:
        raise SystemExit(f"unsupported mutation baseline version {data.get('version')!r}")
    mutations = data.get("mutations") or []
    if not mutations:
        raise SystemExit("the mutation baseline is empty; that would let everything pass")
    for index, mutation in enumerate(mutations):
        missing = {"id", "file", "find", "replace", "classification"} - set(mutation)
        if missing:
            raise SystemExit(f"mutation #{index} is missing {sorted(missing)}")
        if mutation["classification"] not in {"detected", "equivalent", "excepted"}:
            raise SystemExit(
                f"mutation {mutation['id']}: unknown classification "
                f"{mutation['classification']!r}"
            )
        if mutation["classification"] != "detected" and not mutation.get("reason"):
            raise SystemExit(
                f"mutation {mutation['id']}: {mutation['classification']} needs a reason"
            )
    return mutations


def run_tests(package: str) -> tuple[int, list[str], bool]:
    """Run the package's unit tests.

    Returns (exit code, failing test names, build_error). A non-zero exit is not
    evidence on its own: a compiler error also exits non-zero and must never be
    counted as a mutation being detected.
    """
    result = subprocess.run(
        [CARGO, "test", *CARGO_OFFLINE, "-p", package, "--lib"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    failed = sorted(
        {
            line.split(" ... FAILED")[0].removeprefix("test ").strip()
            for line in output.splitlines()
            if line.startswith("test ") and line.rstrip().endswith("FAILED")
        }
    )
    ran = "test result:" in output
    build_error = result.returncode != 0 and (not ran or "could not compile" in output)
    return result.returncode, failed, build_error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--package",
        default="swe-native",
        help="crate the mutations apply to and whose tests must catch them",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="add --offline to cargo; only valid once the dependency cache is warm",
    )
    args = parser.parse_args()
    if args.offline:
        CARGO_OFFLINE.append("--offline")

    mutations = load_manifest(args.manifest)
    baseline_code, baseline_failed, baseline_build = run_tests(args.package)
    if baseline_code != 0:
        print(
            "the suite is not green before mutating, so the gate cannot judge anything "
            f"(build error: {baseline_build}, failing: {baseline_failed})",
            file=sys.stderr,
        )
        return 1

    failures: list[str] = []
    rows: list[tuple[str, str, str, str]] = []
    for mutation in mutations:
        path = ROOT / mutation["file"]
        original = path.read_text()
        digest = sha256(path)
        if mutation["find"] not in original:
            failures.append(
                f"{mutation['id']}: the mutation does not apply "
                f"(no match in {mutation['file']}); refusing to call that a pass"
            )
            rows.append((mutation["id"], mutation["classification"], "NOT APPLIED", ""))
            continue
        mutated = original.replace(mutation["find"], mutation["replace"], 1)
        if mutated == original:
            failures.append(f"{mutation['id']}: replacement produced no change")
            continue
        try:
            path.write_text(mutated)
            code, failed, build_error = run_tests(args.package)
        finally:
            path.write_text(original)
            if sha256(path) != digest:
                raise SystemExit(f"{mutation['id']}: FAILED TO RESTORE {path}")

        classification = mutation["classification"]
        if build_error:
            # A mutation that breaks compilation proves nothing about the tests.
            failures.append(
                f"{mutation['id']}: the mutation produced a build error, not a test "
                "failure; it cannot count as detected"
            )
            rows.append((mutation["id"], classification, "BUILD ERROR", ""))
            continue
        detected = code != 0 and bool(failed)
        if classification == "detected":
            expected = mutation.get("expected_red") or []
            if not expected:
                failures.append(
                    f"{mutation['id']}: a detected mutation must name the tests it is "
                    "expected to redden (expected_red)"
                )
                ok = False
                outcome = "NO EXPECTATION"
            else:
                missing = sorted(set(expected) - set(failed))
                ok = detected and not missing
                outcome = "detected" if ok else "MISSED"
                if not detected:
                    failures.append(
                        f"{mutation['id']}: expected {expected} to fail, the suite stayed green — "
                        "the test that catches this has rotted"
                    )
                elif missing:
                    failures.append(
                        f"{mutation['id']}: expected {missing} to fail, but the red tests were "
                        f"{failed or 'none'} — wrong test was proven"
                    )
        else:
            ok = not detected
            outcome = "equivalent" if ok else "DETECTED BUT MARKED " + classification.upper()
            if detected:
                failures.append(
                    f"{mutation['id']}: classified {classification} but reddened the suite "
                    f"({', '.join(sorted(failed)) or 'unknown test'}); the baseline is stale"
                )
        rows.append(
            (
                mutation["id"],
                classification,
                outcome if ok else "✗ " + outcome,
                ", ".join(sorted(failed)[:3]),
            )
        )

    width = max(len(row[0]) for row in rows) if rows else 10
    print(f"{'mutation'.ljust(width)}  {'class':10}  {'outcome':10}  first failing tests")
    print("-" * (width + 60))
    for name, classification, outcome, tests in rows:
        print(f"{name.ljust(width)}  {classification:10}  {outcome:10}  {tests}")

    if failures:
        print("\nmutation gate FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"\nmutation gate OK: {len(rows)} mutations, every one as classified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""The mutation matrix for the contract gate, run against throwaway git repos.

A gate is only worth what its negative tests prove. Each case builds a small
repository, commits a base, applies one change, commits a head, and runs the
real checker against it — so the matrix exercises the shipped script, not a mock.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "scripts" / "check_contract_freeze.py"

FILES = {
    "python/swe/schema.py": 'SWD_VERSION = "1.0"\n',
    "python/swe/swd_v1.schema.json": '{"type": "object", "properties": {"nodes": {"type": "object"}}}\n',
    "crates/swe-native/src/journal.rs": (
        "pub const JOURNAL_SCHEMA_VERSION: u32 = 1;\n\n"
        "pub enum JournalEvent {\n"
        "    AttemptStarted { attempt_id: String },\n"
        "    ChargeSettled { charge_id: String, amount_milli: u64 },\n"
        "}\n"
    ),
    "crates/swe-native/src/definition.rs": "pub struct CompiledDefinition;\n\npub fn parse() {}\n",
    "crates/swe-native/src/needs.rs": "pub struct NeedRef;\n",
    "crates/swe-native/src/evidence.rs": "pub struct Evidence;\n",
    "crates/swe-native/src/operations.rs": "pub struct OperationSpec;\n\npub fn gate() {}\n",
    "crates/swe-reference/src/journal.rs": "pub const CONTRACT_VERSION: u32 = 1;\n",
    "contracts/swd-v1-workflow.json": '{"nodes": {"plan": {"type": "task"}}, "input": {"question": "x"}}\n',
    "contracts/journal-v1-events.json": '[{"kind": "ChargeSettled", "amount_milli": 500}]\n',
    "contracts/journal-v1-header.json": (
        '{"schema_version": 1, "run_id": "r", "definition_sha256": "aaaa"}\n'
    ),
    "docs/swe-standalone/08-verification-log.md": "# log\n",
}
DECISION = "Kontraktsändring: test\n"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def make_repo(tmp: Path, *, contracts_at_base: bool, omit: set[str] | None = None) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "scripts").mkdir()
    shutil.copy(CHECKER, repo / "scripts" / "check_contract_freeze.py")
    omitted = omit or set()
    for path, content in FILES.items():
        if not contracts_at_base and path.startswith("contracts/"):
            continue
        if path in omitted:
            continue
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    if not contracts_at_base:
        for path, content in FILES.items():
            if path.startswith("contracts/"):
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
    return repo


def commit(repo: Path, changes: dict[str, str | None], message: str = "change") -> None:
    for path, content in changes.items():
        target = repo / path
        if content is None:
            if target.exists():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def run(repo: Path) -> int:
    # Run the shipped checker against the throwaway repo; the root override is
    # what lets the gate be tested without copying it into the fixture.
    return subprocess.run(
        [sys.executable, str(CHECKER), "--base", "HEAD~1", "--head", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**subprocess.os.environ, "CONTRACT_FREEZE_ROOT": str(repo)},
    ).returncode


CASES = []


def case(name: str, expect: int):
    def register(fn):
        CASES.append((name, expect, fn))
        return fn

    return register


@case("docs/frontend-only PR: no contract path touched", 0)
def _(repo: Path) -> None:
    commit(repo, {"docs/readme.md": "hello\n"})


@case("guard script deleted: fails", 1)
def _(repo: Path) -> None:
    commit(repo, {"scripts/check_contract_freeze.py": None})


@case("journal wire changed + SWD bumped: fails", 1)
def _(repo: Path) -> None:
    commit(
        repo,
        {
            "contracts/journal-v1-events.json": '[{"kind": "ChargeSettled", "amount": 500}]\n',
            "python/swe/schema.py": 'SWD_VERSION = "1.1"\n',
            "docs/swe-standalone/08-verification-log.md": DECISION,
        },
    )


@case("SWD wire changed + journal bumped: fails", 1)
def _(repo: Path) -> None:
    commit(
        repo,
        {
            "contracts/swd-v1-workflow.json": '{"nodes": {"planner": {"type": "task"}}}\n',
            "crates/swe-native/src/journal.rs": FILES["crates/swe-native/src/journal.rs"].replace("= 1;", "= 2;"),
            "docs/swe-standalone/08-verification-log.md": DECISION,
        },
    )


@case("operations API changed + only journal bumped: fails", 1)
def _(repo: Path) -> None:
    commit(
        repo,
        {
            "crates/swe-native/src/operations.rs": "pub struct OperationSpec;\n\npub fn gate(strict: bool) {}\n",
            "crates/swe-native/src/journal.rs": FILES["crates/swe-native/src/journal.rs"].replace("= 1;", "= 2;"),
            "docs/swe-standalone/08-verification-log.md": DECISION,
        },
    )


@case("operations API + CONTRACT_VERSION bumped: passes without a journal bump", 0)
def _(repo: Path) -> None:
    commit(
        repo,
        {
            "crates/swe-native/src/operations.rs": "pub struct OperationSpec;\n\npub fn gate(strict: bool) {}\n",
            "crates/swe-reference/src/journal.rs": "pub const CONTRACT_VERSION: u32 = 2;\n",
            "docs/swe-standalone/08-verification-log.md": DECISION,
        },
    )


@case("comment/test only in journal.rs: no bump", 0)
def _(repo: Path) -> None:
    commit(
        repo,
        {
            "crates/swe-native/src/journal.rs": (
                FILES["crates/swe-native/src/journal.rs"] + "\n// clarified the comment\n"
            ),
            "docs/swe-standalone/08-verification-log.md": DECISION,
        },
    )


@case("header example value changed, form identical: no bump", 0)
def _(repo: Path) -> None:
    commit(
        repo,
        {
            "contracts/journal-v1-header.json": (
                '{"schema_version": 1, "run_id": "other", "definition_sha256": "bbbb"}\n'
            ),
            "docs/swe-standalone/08-verification-log.md": DECISION,
        },
    )


@case("header key renamed: journal bump required", 1)
def _(repo: Path) -> None:
    commit(
        repo,
        {
            "contracts/journal-v1-header.json": (
                '{"schema_version": 1, "run": "r", "definition_sha256": "aaaa"}\n'
            ),
            "docs/swe-standalone/08-verification-log.md": DECISION,
        },
    )


@case("header key renamed and JOURNAL_SCHEMA_VERSION bumped: passes", 0)
def _(repo: Path) -> None:
    commit(
        repo,
        {
            "contracts/journal-v1-header.json": (
                '{"schema_version": 2, "run": "r", "definition_sha256": "aaaa"}\n'
            ),
            "crates/swe-native/src/journal.rs": FILES["crates/swe-native/src/journal.rs"].replace("= 1;", "= 2;"),
            "docs/swe-standalone/08-verification-log.md": DECISION,
        },
    )


@case("no documented decision: fails", 1)
def _(repo: Path) -> None:
    commit(repo, {"crates/swe-native/src/operations.rs": "pub fn gate(strict: bool) {}\n"})


def bootstrap_cases() -> list[tuple[str, int, callable]]:
    def bootstrap_ok(repo: Path) -> None:
        commit(
            repo,
            {
                "python/swe/schema.py": 'SWD_VERSION = "2.0"\n',
                "contracts/journal-v1-events.json": '[{"kind": "AttemptStarted", "attempt_id": "a"}]\n',
                "docs/swe-standalone/08-verification-log.md": DECISION,
            },
        )

    def post_bootstrap_fails(repo: Path) -> None:
        commit(
            repo,
            {
                "python/swe/schema.py": 'SWD_VERSION = "1.0"\n',
                "contracts/journal-v1-events.json": '[{"kind": "AttemptStarted", "attempt_id": "a"}]\n',
                "docs/swe-standalone/08-verification-log.md": DECISION,
            },
        )

    def moved_version_file(repo: Path) -> None:
        # The version constant lives in a file that did not exist at the base
        # (a package move in the same PR). Bootstrap must not fail on that.
        commit(
            repo,
            {
                "python/swe/schema.py": 'SWD_VERSION = "1.0"\n',
                "docs/swe-standalone/08-verification-log.md": DECISION,
            },
        )

    return [
        ("bootstrap: version file moved in this PR: allowed", 0, moved_version_file),
        ("bootstrap: contracts absent at base: version 1 allowed", 0, bootstrap_ok),
        ("post-bootstrap: same change with contracts at base: fails", 1, post_bootstrap_fails),
    ]


def main() -> int:
    failures = 0
    for name, expect, mutate in [*CASES, *bootstrap_cases()]:
        with tempfile.TemporaryDirectory() as tmp:
            # The bootstrap cases need contracts absent at the base commit; the
            # others need them present so they are not exempted by bootstrap.
            omit = {"python/swe/schema.py"} if "version file moved" in name else None
            repo = make_repo(
                Path(tmp),
                contracts_at_base="post-bootstrap" in name or "bootstrap" not in name,
                omit=omit,
            )
            mutate(repo)
            code = run(repo)
            ok = code == expect
            failures += 0 if ok else 1
            print(f"{'PASS' if ok else 'FAIL'}  expected {expect} got {code}  {name}")
    print(f"\n{len(CASES) + 2} cases, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

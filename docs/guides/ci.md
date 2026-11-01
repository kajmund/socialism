# Continuous integration

GitHub Actions runs the test suite on every pull request, on every push to `main` (including merges), and on merge-queue groups. The workflow is [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml).

## What runs

| Job | Command | Notes |
| --- | --- | --- |
| Backend tests | `cd backend && uv sync --frozen && uv run ruff check app tests scripts/check_maintainability.py ../python/swe ../python/tests && uv run python scripts/check_maintainability.py && uv run pytest -m "not smoke and not research_reuse and not swe_runtime"` | In-memory SQLite. Smoke tests (`-m smoke`) stay opt-in. Ruff + the module-length/`# noqa` budget run before pytest. Research-reuse contracts and `swe_runtime` consumer tests run in their dedicated jobs. |
| Research reuse contracts | `uv run pytest tests/research_reuse -m research_reuse` | Four-step Graph v2 reuse contracts with mocked external boundaries. |
| SWE runtime | `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, `cargo test --workspace`, `cargo run -p swe-reference`, `scripts/check_contract_freeze.py` (on contract changes), the two gate self-test matrices, `maturin develop`, `pytest ../python/tests`, then the backend `-m swe_runtime` consumer tests | Rust kernel workspace, PyO3 extension, frozen contracts, SWD/runtime tests, and the backend consumer tests against the installed package. |
| Python SWE package | `uv sync --locked --group dev`, `maturin build`, `uv run --no-sync pytest -m "not smoke"`, then `uv build` and install the wheel into a clean venv outside the repo | The package proves itself in its own environment, and the built distribution must install and find its packaged schema data. |
| SWE mutation gate | `cargo fetch --locked`, then `python3 scripts/check_mutations.py --offline` | Every critical kernel mutation is classified `detected`/`equivalent`/`excepted`; a mutation that does not behave as classified fails CI. See [docs/swe-standalone/14-mutation-gate.md](../swe-standalone/14-mutation-gate.md). |
| Swe-gym tests | `cargo fmt --check` + `cargo test` in `crates/swe-gym` | Separate crate with its own workspace root and governance; also runs when the core crates it path-depends on change. |
| PostgreSQL schema | `alembic upgrade head` + the marked PostgreSQL integration tests | |
| Frontend tests | `pnpm install --frozen-lockfile`, then `pnpm lint`, `pnpm test` | oxlint + existing vitest files. |
| Word add-in tests | `cd word-addin && pnpm install --frozen-lockfile`, then lint + vitest + `tsc -b` | No Word host; section/dedupe unit tests only. |
| Knowledge validate | `make knowledge-validate` | OKF manuals must stay valid. |
| **CI** | Aggregates the jobs above | This is the required status check. Unselected jobs are allowed to be `skipped`; a gate that the change selector required (the mutation gate when core files changed, the contract guard when a contract path changed) must be `success`. |

No network LLM calls. Dummy keys are set in `backend/tests/conftest.py`. The mutation gate resolves the locked crate set once and then runs offline.

## Local equivalent

```bash
make test             # backend + frontend + word-addin
make test-swe         # Rust workspace, gate self-tests, Python package + consumer tests
make mutation-gate    # classified mutation gate (offline after one cargo fetch)
make contract-gate    # contract freeze gate against origin/main plus its matrix
make knowledge-validate
```

Or the same commands CI uses, from each package directory.

## Merge gate

A pull request must not merge while **CI** is red or pending.

GitHub only enforces that when a [ruleset](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository) (or classic branch protection) requires the `CI` check on the default branch. Repo admins set that once:

1. Wait until this workflow has run at least once (so GitHub lists the `CI` check).
2. Repo **Settings → Rules → Rulesets → New branch ruleset**.
3. Target: default branch (`main`).
4. Enable **Require status checks to pass** and add the check named `CI`.
5. Enable **Require branches to be up to date before merging**.
6. Enforcement: Active. Save.

Equivalent API (needs `admin:repo` / ruleset write):

```bash
gh api --method POST repos/kajmund/socialism/rulesets \
  --input - <<'EOF'
{
  "name": "Require CI",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["~DEFAULT_BRANCH"],
      "exclude": []
    }
  },
  "rules": [
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "do_not_enforce_on_create": false,
        "required_status_checks": [
          { "context": "CI" }
        ]
      }
    }
  ]
}
EOF
```

Do not add bypass actors unless you explicitly want someone to merge with a red suite.

Live OASIS smoke (`uv run pytest -m smoke`) is still a manual pre-release check — see [backend-setup.md](backend-setup.md).

# Continuous integration

GitHub Actions runs the test suite on every pull request, on every push to `main` (including merges), and on merge-queue groups. The workflow is [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml).

## What runs

| Job | Command | Notes |
| --- | --- | --- |
| Backend tests | `cd backend && uv sync --frozen && uv run ruff check app tests scripts/check_maintainability.py && uv run python scripts/check_maintainability.py && uv run pytest -m "not smoke and not research_reuse and not swe_runtime"` | In-memory SQLite. Smoke tests (`-m smoke`) stay opt-in. Ruff + the module-length/`# noqa` budget run before pytest. Research-reuse contracts and `swe_runtime` consumer tests run in their dedicated jobs. |
| Research reuse contracts | `uv run pytest tests/research_reuse -m research_reuse` | Four-step Graph v2 reuse contracts with mocked external boundaries. |
| SWE consumer contracts | Build `swe_native` from the pinned `kajmund/swe` revision, then run the backend `-m swe_runtime` contract tests | Confirms the Python git dependency and native source are the same revision, runs a workflow, exercises Socialism's adapters, and rejects a local engine copy. SWE's package, contract-freeze and mutation gates run in the standalone repository. |
| Swe-gym tests | `cargo fmt --check` + `cargo test --locked` in `crates/swe-gym` | Separate crate with its own governance, consuming `swe-native` and `swe-budget` from the same pinned git revision. |
| PostgreSQL schema | `alembic upgrade head` + the marked PostgreSQL integration tests | |
| Frontend tests | `pnpm install --frozen-lockfile`, then `pnpm lint`, `pnpm test` | oxlint + existing vitest files. |
| Word add-in tests | `cd word-addin && pnpm install --frozen-lockfile`, then lint + vitest + `tsc -b` | No Word host; section/dedupe unit tests only. |
| Knowledge validate | `make knowledge-validate` | OKF manuals must stay valid. |
| **CI** | Aggregates the jobs above | This is the required status check. Unselected jobs are allowed to be `skipped`. |

No network LLM calls. Dummy keys are set in `backend/tests/conftest.py`. Package downloads and the pinned public SWE git revision are the only dependency network access.

## Local equivalent

```bash
make test             # backend + frontend + word-addin
make test-swe         # pinned SWE build + Socialism consumer contracts
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

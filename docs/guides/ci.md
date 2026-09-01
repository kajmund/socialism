# Continuous integration

GitHub Actions runs the test suite on every pull request, on every push to `main` (including merges), and on merge-queue groups. The workflow is [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml).

## What runs

| Job | Command | Notes |
| --- | --- | --- |
| Backend tests | `cd backend && uv sync --frozen && uv run pytest` | In-memory SQLite. Smoke tests (`-m smoke`) stay opt-in and are not run. |
| Frontend tests | `pnpm install --frozen-lockfile`, then `pnpm lint`, `pnpm test` | oxlint + existing vitest files. |
| Knowledge validate | `make knowledge-validate` | OKF manuals must stay valid. |
| **CI** | Aggregates the jobs above | This is the required status check. It fails if any job failed or was skipped. |

No network LLM calls. Dummy keys are set in `backend/tests/conftest.py`.

## Local equivalent

```bash
make test
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

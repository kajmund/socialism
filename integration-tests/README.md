# Live checks against real services

## Workspace research

`check_workspace_research_live.py` exercises the actual authenticated API,
document ingest worker, editable Q&A, canonical passage grounding, chat model
tool calls, and Attempt research engine. PostgreSQL, object storage, Storage
Vectors, embeddings and chat models use the configured services.

Run from the repository root with the backend environment installed:

```sh
WORKSPACE_LIVE_ENV_FILE=/absolute/path/to/backend/.env \
  backend/.venv/bin/python integration-tests/check_workspace_research_live.py
```

The environment must provide the application and migration database URLs,
storage/vector credentials and configured model credentials. The runner creates
a random database schema and a synthetic organisation with two client
workspaces. Every application transaction explicitly selects that schema,
including connections returned by the transaction pooler. It verifies schema
ownership before seeding. The vector type/operator in the test schema delegates
to the installed PostgreSQL vector extension.

Migration checks exercise workspace backfill, uniqueness, foreign keys,
membership, tenant question namespaces and backend-only privileges, then roll
back their fixtures before the API checks. Application fixtures use the normal
SQLAlchemy metadata in the same isolated schema.

The checks cover company defaults, sibling workspace rejection, Q&A revision
and original passage identity, unchanged-content re-ingest, separate global
knowledge, the same frozen document manifest through both research entry
points, clickable canonical citations and persisted reply idempotency. External
calls record whether their calling task holds a database connection.

The report is saved as `workspace-research-live.json`. A failed assertion exits
with an error after cleanup. Exact object keys and vector keys are recorded
before writes, deleted and checked after the run; only the generated database
schema is dropped. No shared vector index is deleted.
The run also removes its captured standard storage bucket after verifying every recorded object is absent and the exact bucket is empty, then confirms the bucket returns 404.

For a local browser check, start the isolated backend separately:

```sh
WORKSPACE_LIVE_ENV_FILE=/absolute/path/to/backend/.env \
  backend/.venv/bin/python integration-tests/workspace_live_runtime.py --serve
```

It listens on `127.0.0.1:8317`; the frontend uses its normal local login and a
Vite proxy pointed at that backend. Shut it down with a POST to
`/__workspace_shutdown` so the runner finishes resource cleanup.

Generated reports and fixture inventories stay local; credentials and tokens
are never written to them.

## Ollama Cloud clef decision model — quality and latency

`check_clef_cloud_live.py` sends a golden set of 15 Swedish political-messaging
cases (5 choice, 5 noul, 5 score) to Ollama Cloud's `/v1/systemone` endpoint
with `clef:cloud` and measures decision accuracy against expected answers and
per-call latency. One HTTP call per case. Run from the repository root:

```sh
backend/.venv/bin/python integration-tests/check_clef_cloud_live.py
```

Requires `OLLAMA_API_KEY` (process environment or `backend/.env`; create the
key at <https://ollama.com/settings/keys>). Every run is metered — it makes 15
real API calls.

Exit codes: `0` when every case completed and overall accuracy met the floor;
`1` when a case failed, timed out, or accuracy was below the floor; `2` on
configuration or authentication errors. Flags: `--model` (default
`clef:cloud`), `--base-url` (default `https://ollama.com`), `--timeout`
(default 30 s — the only hard time boundary; latency is reported as
min/median/p95/max/mean), `--min-accuracy` (default 0.8), `--env-file`,
`--report`. The report is saved as `clef-cloud-live.json` (gitignored);
credentials are never written to it. The check is text-only by design; clef
image judgment is not exercised.

## Decision-model A/B: clef:cloud vs Jev

`check_clef_vs_jev_live.py` runs the same golden set against Ollama Cloud
`clef:cloud` and TypeSafe `jev-latest` — the model that currently drives Auto
classification in the backend — and writes a side-by-side report
(`clef-vs-jev-live.json`, gitignored). Both models share the `/v1/systemone`
protocol; the runner and cases live in `decision_check_core.py`.

```sh
backend/.venv/bin/python integration-tests/check_clef_vs_jev_live.py
```

Requires both `OLLAMA_API_KEY` and `TYPESAFE_API_KEY` (process environment or
`backend/.env`). Every run is metered — 30 real API calls. Flags:
`--clef-model` (default `clef:cloud`), `--jev-model` (default `jev-latest`),
`--clef-base-url` (default `https://ollama.com`), `--jev-base-url` (default
`https://api.typesafe.ai`), `--timeout`, `--min-accuracy`, `--env-file`,
`--report`. Exit `0` when both models complete and meet the accuracy floor;
`1` on quality failures; `2` on configuration or authentication errors.

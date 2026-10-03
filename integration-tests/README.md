# Workspace research with real services

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

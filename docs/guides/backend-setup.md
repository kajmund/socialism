# Backend setup

Python + FastAPI admin API for Opinionssimulator: personas, populations, runs, messages (budskap), catalog (grunddata), background jobs, and reports. The frontend talks to it over JSON via `VITE_API_BASE_URL`.

See [architecture.md](../architecture.md) for domain and run lifecycle. For interviews, branch modes (`ab` / `stimulus_control`), message freeze, lexical `quality_warnings`, and persona anecdotes, see [runs-interviews-and-quality.md](runs-interviews-and-quality.md).

## Phase 1: SQLite

Local development uses SQLite (`aiosqlite`) so you can run without Supabase. SQLAlchemy models + Alembic migrations stay portable — later swap `DATABASE_URL` to Supabase Postgres.

## Init

```bash
cd backend
uv sync
cp .env.example .env
```

### Environment

| Variable | Required | Default | Notes |
| -------- | -------- | ------- | ----- |
| `DATABASE_URL` | no | `sqlite+aiosqlite:///./data/opinionssimulator.db` | Relative paths resolve from process cwd (usually `backend/`) |
| `ALLOWED_ORIGINS` | no | Vite localhost origins | Comma-separated CORS list |
| `DEEPSEEK_API_KEY` | **yes** | — | App will not boot without a non-empty key |
| `DEEPSEEK_MODEL` | no | `deepseek-chat` | |
| `DEEPSEEK_BASE_URL` | no | `https://api.deepseek.com` | |
| `DEEPSEEK_TIMEOUT_SECONDS` | no | `60` | HTTP timeout for DeepSeek calls (hangs reports if too low/high) |
| `PERSONA_GENERATOR` | no | `deepseek` | `stub` = weighted random for offline persona *sampling* in tests only |
| `SIMULATION_ENGINE` | no | `none` | `none` = empty attempt on start; `oasis` = live CAMEL OASIS |

`.env` example:

```env
DATABASE_URL=sqlite+aiosqlite:///./data/opinionssimulator.db
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_TIMEOUT_SECONDS=60
PERSONA_GENERATOR=deepseek
SIMULATION_ENGINE=none
```

Constraints:

- `DEEPSEEK_API_KEY` is required at startup even when `PERSONA_GENERATOR=stub`. There is no keyword/heuristic LLM fallback for chat or reports.
- Settings live only in `app/config.py` — do not call `os.getenv` / `load_dotenv` in app code.

## Optional: OASIS simulation

Default `SIMULATION_ENGINE=none` flips run status via a background job with an empty results attempt (fast local loop).

For live multi-agent sims:

```bash
cd backend
uv sync --extra oasis   # heavy: CAMEL + torch
# set SIMULATION_ENGINE=oasis in .env
```

Then `POST /runs/{id}/start` queues `run_simulate` and runs the full population + injectors across all configured ticks. Per-run `oasis_options.platform` selects `twitter` (default) or `reddit`.

CLI smoke: `uv run python -m app.services.oasis_run --run-id N`.

## Database migrations

Alembic owns schema changes:

```bash
uv run alembic revision --autogenerate -m "describe change"
# review the generated file, then:
uv run alembic upgrade head
```

SQLite needs `render_as_batch=True` (already set in `alembic/env.py`) for alter-table operations.

## Seed demo data

```bash
uv run python -m app.seed
```

Loads personas / populations / runs shaped like the frontend mock library.

## Run

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.seed
uv run uvicorn app.main:app --reload
```

- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

## Public API map

| Router | Examples |
| ------ | -------- |
| Personas | `GET/POST /personas`, generate, chat, message delete/resend |
| Populations | CRUD, generate, members, duplicate |
| Runs | CRUD, `POST /runs/{id}/start` (202 + job), attempt delete, post-hoc interviews (`/attempts/.../interview`) |
| Messages | Budskapsbibliotek, summarize-url, generate-variants |
| Catalog | `GET/PUT /catalog/{key}` |
| Jobs | `POST/GET /jobs`, `GET /jobs/{id}` |
| Reports | `POST /reports` (202), `GET /reports/{id}/html` |

Personas also expose library chat delete/resend (`DELETE …/messages`, `POST …/messages/{id}/resend`). Full interview/branch/quality runbook: [runs-interviews-and-quality.md](runs-interviews-and-quality.md).

### Background jobs

Kinds: `population_generate`, `run_simulate`, `report_generate`.

- Created by population generate, run start, and report create.
- Polled via `/jobs` (admin UI at `/jobs`).
- On backend startup, interrupted in-flight jobs are marked failed (skipped if DB not migrated yet).

### Reports

`POST /reports` with `{ "sources": [{ "run_id": 1, "attempt_id": "..." }], "title": "..." }` queues generation. Hybrid HTML = deterministic metrics/charts + LLM narrative. Artifacts under `backend/data/reports/{id}/`.

## Imports (`from app...`)

`backend/app` is installed as an editable package by `uv sync`, so `from app...` imports work from uvicorn, tests, and scripts.

## Tests

```bash
cd backend
uv run pytest
```

Uses in-memory SQLite; no network required. Tests set a dummy `DEEPSEEK_API_KEY` and mock the LLM client.

## Troubleshooting

| Symptom | Likely cause |
| ------- | ------------ |
| App exits immediately on boot | Missing/empty `DEEPSEEK_API_KEY` |
| CORS errors from Vite | `ALLOWED_ORIGINS` missing the browser origin |
| Start returns 400 about OASIS | `SIMULATION_ENGINE=oasis` without `uv sync --extra oasis` or without DeepSeek key mirroring |
| Start returns 400 about missing message | Injection `message_id` not in budskapsbibliotek — fix before start (bodies are frozen then) |
| Post-hoc interview 409 / tick errors | Run still simulating, or `through_tick_index` out of range — see [interview runbook](runs-interviews-and-quality.md) |
| Jobs stuck after crash | Restart API — interrupted jobs are failed on lifespan startup |
| Report job hangs | Raise/check `DEEPSEEK_TIMEOUT_SECONDS`; confirm DeepSeek reachability |
| SQLite alter migration fails | Ensure `render_as_batch=True` and review autogenerated revision |

## Later: Supabase Postgres

When moving off SQLite:

1. Point `DATABASE_URL` at the direct Supabase Postgres URL (session mode, not the transaction pooler).
2. Add `psycopg` (and later Auth as needed).
3. Re-run `alembic upgrade head` against Postgres.
4. Do not treat the Supabase dashboard as the schema source of truth — Alembic remains authoritative.

See [supabase-setup.md](supabase-setup.md).

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
| `OPENAI_API_KEY` | **yes** | — | OpenAI embeddings for SSR reports (separate from DeepSeek) |
| `EMBEDDING_MODEL` | no | `text-embedding-3-large` | |
| `EMBEDDING_BASE_URL` | no | `https://api.openai.com/v1` | |
| `EMBEDDING_TIMEOUT_SECONDS` | no | `60` | |
| `PERSONA_GENERATOR` | no | `deepseek` | `stub` = weighted random for offline persona *sampling* in tests only |
| `SIMULATION_ENGINE` | no | `none` | `none` = empty attempt on start; `oasis` = live CAMEL OASIS |
| `MAX_CONCURRENT_SIMULATION_JOBS` | no | `2` | Cap overlapping `run_simulate` jobs (1–32). A/B variants inside one job still run in parallel |

`.env` example:

```env
DATABASE_URL=sqlite+aiosqlite:///./data/opinionssimulator.db
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_TIMEOUT_SECONDS=60
OPENAI_API_KEY=sk-...
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_TIMEOUT_SECONDS=60
PERSONA_GENERATOR=deepseek
SIMULATION_ENGINE=none
MAX_CONCURRENT_SIMULATION_JOBS=2
```

Constraints:

- `DEEPSEEK_API_KEY` is required at startup even when `PERSONA_GENERATOR=stub`. There is no keyword/heuristic LLM fallback for chat or reports.
- `OPENAI_API_KEY` is required for Semantic Similarity Rating (report tone/style). The SSR embeddings client reads `settings.openai_api_key` explicitly — not the process env after OASIS mirrors DeepSeek into `OPENAI_API_KEY`.
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

Adapter layers, phased decoupling from camel-oasis internals, and an upgrade checklist: [simulation-engine-layers.md](simulation-engine-layers.md).

CLI smoke (persists attempt on the körning): `uv run python -m app.services.oasis_run --run-id N`.

### Simulation smoke harness (manual)

End-to-end check against **live** camel-oasis + DeepSeek before a release or after upgrading camel-oasis. Not run in default CI.

```bash
cd backend
uv sync --extra oasis
# DEEPSEEK_API_KEY must be a real key in backend/.env or the environment
uv run pytest -m smoke
# or:
uv run python scripts/run_simulation_smoke.py
```

Fixture: self-contained 5-persona population, 2 ticks (tick 2 reaction-only), 1 party-post injection on Twitter. Asserts attempt shape, readback (posts/trace/histogram), and no variant error — not LLM-specific engagement transitions (those stay in unit tests).

Default `uv run pytest` excludes smoke via `addopts = "-m 'not smoke'"` in `pyproject.toml`.

### Benchmark DeepSeek models

Compare wall time and OASIS output metrics across model IDs for the **same** run config (default: `deepseek-reasoner` vs `deepseek-chat`):

```bash
cd backend
uv sync --extra oasis
# DEEPSEEK_API_KEY must be a real key (placeholder values are rejected)
uv run python scripts/benchmark_simulation_models.py --run-id 3
uv run python scripts/benchmark_simulation_models.py --run-id 3 \
  --models deepseek-reasoner deepseek-chat \
  --output data/benchmark_simulation_models.json
```

Intent: pick a model for live sims by measuring latency and activity (trace events, posts, comments, action histogram) on a representative körning.

Constraints (verified against `scripts/benchmark_simulation_models.py`):

- Calls `simulate_run` once per model; mutates in-process `settings.deepseek_model` between runs (do not share that process with a live API server you expect to keep a fixed model).
- Does **not** update `run.status` / `run.results` in SQLite — unlike `python -m app.services.oasis_run`. Use the JSON output (default `data/benchmark_simulation_models.json`) for comparison.
- Still writes/overwrites OASIS artifacts under `data/oasis/run_{id}/…` (same paths as a normal OASIS sim).
- Requires the `oasis` extra, a seeded run id that exists, and a non-placeholder `DEEPSEEK_API_KEY`. Failures surface as `status: failed` with an `error` string per model — no alternate-model fallback.

### Benchmark prompt configurations (engagement balance)

Compare like/dislike balance, SSR tone/style, and Gini for the **same** körning while varying `oasis.agents.action_rules` on dedicated benchmark Configuration rows (baseline, symmetric like rule, restructured comment list, list-only):

```bash
cd backend
uv sync --extra oasis
# DEEPSEEK_API_KEY + OPENAI_API_KEY required (SSR tone/style is mandatory)
uv run python scripts/benchmark_prompt_configurations.py --run-id 7 \
  --repetitions 5 --boost-rounds 2
```

Recommended seed körning: **Prompt benchmark — volym** (`run_id=7` after fresh seed) — all 12 demo personas, two ticks × three reaction rounds each.

Use `--mechanics-only` to create/update the four benchmark Configuration rows without simulating (no API keys). Do **not** use `--skip-ssr` for real comparisons — winner criteria need `critical_tone_share` and `sarcasm_style_share`.

Constraints (verified against `scripts/benchmark_prompt_configurations.py`):

- Creates or updates named Configuration rows under **Konfigurationer**; activates each in turn and restores the previous active config when finished.
- Runs each variant `--repetitions` times (default 5), aggregates mean ± std for like_ratio, critical_tone_share, and sarcasm_style_share.
- `--boost-rounds N` multiplies each tick's reaction rounds in-memory (does not persist) for more engagement events per run.
- Declares a **winner** only when a variant beats baseline mean like_ratio **and** keeps ≥70% of baseline critical tone (configurable via `--critical-retention`); otherwise reports *inget tydligt resultat*.
- Calls `simulate_run` per repetition; does **not** persist attempts on the run row (same as model benchmark).
- Writes JSON to `data/benchmark_prompt_configurations.json` with per-repetition runs, aggregates, conclusion, and overcorrection warnings.

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
| Jobs | `POST/GET /jobs`, `GET /jobs/{id}`, `WS /ws/jobs` |
| Chat | `WS /ws/chat` (streaming library + run interview) |
| Reports | `POST /reports` (202), `GET /reports/{id}/html` |

Personas also expose library chat delete/resend (`DELETE …/messages`, `POST …/messages/{id}/resend`). Full interview/branch/quality runbook: [runs-interviews-and-quality.md](runs-interviews-and-quality.md).

### Background jobs

Kinds: `population_generate`, `run_simulate`, `report_generate`.

- Created by population generate, run start, and report create.
- Admin UI subscribes to `WS /ws/jobs` for live updates (REST `GET /jobs` remains for one-shot reads).
- On backend startup, interrupted in-flight jobs are marked failed (skipped if DB not migrated yet).


### Reports

`POST /reports` with `{ "sources": [{ "run_id": 1, "attempt_id": "..." }], "title": "..." }` queues generation. HTML = deterministic metrics/charts + SSR tone/style (embeddings) + threshold templates. Artifacts under `backend/data/reports/{id}/`.

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
| Benchmark exits about API key | Missing/placeholder `DEEPSEEK_API_KEY` in `backend/.env` |
| Benchmark `OasisUnavailable` | Run `uv sync --extra oasis`; confirm camel-oasis import works |
| Benchmark JSON ok but UI unchanged | Script does not persist attempts — check `data/benchmark_*.json`, not the körning detail page |
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

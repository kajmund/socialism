# Backend setup

Python + FastAPI admin API for Opinionssimulator: personas, populations, runs, messages (budskap), catalog (grunddata), background jobs, and reports. The frontend talks to it over JSON via `VITE_API_BASE_URL`.

See [architecture.md](../architecture.md) for domain and run lifecycle. For interviews, branch modes (`ab` / `stimulus_control`), message freeze, lexical `quality_warnings`, and persona anecdotes, see [runs-interviews-and-quality.md](runs-interviews-and-quality.md).

## Database

Runtime environments use Supabase Postgres. The fast unit-test suite still uses isolated in-memory SQLite databases. SQLAlchemy models and Alembic are the schema source of truth for both dialects.

## Init

```bash
cd backend
uv sync
cp .env.example .env
```

### Environment

| Variable | Required | Default | Notes |
| -------- | -------- | ------- | ----- |
| `DATABASE_URL` | **yes** | — | Use the Supabase direct/session URL. `postgres://` and `postgresql://` are normalized to the psycopg driver. Do not use the transaction pooler for the long-running backend. Session-mode pooler (`*.pooler.supabase.com:5432`) caps clients at 15; the backend keeps SQLAlchemy and Mem0 well below that. |
| `MIGRATION_DATABASE_URL` | **for Alembic** | — | Direct/session URL for the table owner (`postgres`), using that role's database password. Alembic never uses the runtime `DATABASE_URL`. Keep this credential backend-only. |
| `ALLOWED_ORIGINS` | no | Vite localhost origins | Comma-separated CORS list |
| `LLM_PROVIDER` | no | `cerebras` | `cerebras` or `deepseek`. No automatic fallback |
| `LLM_MODEL` | no | provider default | Empty → `gpt-oss-120b` (Cerebras) or `DEEPSEEK_MODEL` |
| `LLM_REASONING_EFFORT` | no | `medium` | Sent only when the selected provider/model supports it (Cerebras) |
| `LLM_MAX_TOKENS` | no | `8192` | Completion cap for structured JSON (`complete_structured`) |
| `LLM_TIMEOUT_SECONDS` | no | `60` | HTTP timeout for chat/completions |
| `DOCUMENT_KNOWLEDGE_LLM_MAX_TOKENS` | no | `8192` | Per-batch completion cap for generated document facts/Q&A; does not inherit a larger global cap |
| `DOCUMENT_KNOWLEDGE_LLM_TIMEOUT_SECONDS` | no | `180` | Per-batch timeout for generated document facts/Q&A |
| `CEREBRAS_API_KEY` | **when `LLM_PROVIDER=cerebras`** | — | App will not boot without a non-empty key |
| `CEREBRAS_BASE_URL` | no | `https://api.cerebras.ai/v1` | |
| `DEEPSEEK_API_KEY` | **when `LLM_PROVIDER=deepseek`** (also OASIS) | — | Same `app.llm` path; required for OASIS regardless of chat provider |
| `DEEPSEEK_MODEL` | no | `deepseek-chat` | Used when `LLM_PROVIDER=deepseek` and `LLM_MODEL` is empty |
| `DEEPSEEK_BASE_URL` | no | `https://api.deepseek.com` | |
| `TYPESAFE_API_KEY` | no | empty | Jev Auto classifier. Empty key makes Auto fall back to the prompt/default config |
| `TYPESAFE_BASE_URL` | no | `https://api.typesafe.ai` | |
| `JEV_MODEL` | no | `jev-latest` | TypeSafe System One model |
| `JEV_CONFIDENCE_THRESHOLD` | no | `0.6` | Below this, Auto uses the prompt/default fallback config |
| `JEV_TIMEOUT_SECONDS` | no | `3` | Jev HTTP timeout |
| `JEV_STATE_CHAR_BUDGET` | no | `8000` | Max message text sent to Jev |
| `RESEARCH_JEV_ENABLED` | no | `false` | Jev research control layer. Also requires `TYPESAFE_API_KEY` |
| `RESEARCH_JEV_MODE` | no | `shadow` | `shadow` compares Jev to the current LLM; `active` may skip assessor/completeness LLM |
| `RESEARCH_JEV_MODEL` | no | `jev-1.12` | System One model for research control only |
| `RESEARCH_JEV_SUFFICIENT_THRESHOLD` | no | `0.9` | High bar before Jev may treat state as sufficient/complete |
| `RESEARCH_JEV_INCOMPLETE_THRESHOLD` | no | `0.85` | High bar for a confident insufficient/incomplete decision |
| `RESEARCH_JEV_CONFIDENCE_THRESHOLD` | no | `0.8` | Minimum Noul confidence before a directional Jev decision |
| `RESEARCH_JEV_MAX_EVIDENCE_ITEMS` | no | `24` | Evidence rows in one compact Jev state |
| `RESEARCH_JEV_MAX_STATE_CHARS` | no | `6000` | Hard cap for compact Jev state JSON |
| `RESEARCH_JEV_CONCURRENCY` | no | `8` | Bounded parallel evidence-screen System One calls |
| `RESEARCH_JEV_TIMEOUT_SECONDS` | no | `5` | Research Jev HTTP timeout |
| `RESEARCH_JEV_EVIDENCE_SCREEN_ENABLED` | no | `true` | Shadow-score retrieved evidence. Never deletes evidence |
| `OPENAI_API_KEY` | **yes** | — | OpenAI embeddings for SSR reports (separate from chat LLM) |
| `EMBEDDING_MODEL` | no | `text-embedding-3-large` | |
| `EMBEDDING_BASE_URL` | no | `https://api.openai.com/v1` | |
| `EMBEDDING_TIMEOUT_SECONDS` | no | `60` | |
| `PERSONA_GENERATOR` | no | `deepseek` | `stub` = weighted random for offline persona *sampling* in tests only |
| `SIMULATION_ENGINE` | no | `none` | `none` = empty attempt on start; `oasis` = live CAMEL OASIS |
| `MAX_CONCURRENT_SIMULATION_JOBS` | no | `2` | Cap overlapping `run_simulate` jobs (1–32). A/B variants inside one job still run in parallel |
| `WORD_REVIEW_MAX_CONCURRENCY` | no | `8` | Cap concurrent Word-review LLM calls inside one expertgranskning job (1–32) |
| `LOG_DIR` | no | `data/logs` | Rotating API log directory (empty = no file). Relative to process cwd |
| `LOG_MAX_BYTES` | no | `2000000` | Rotate `app.log` after this many bytes |
| `LOG_BACKUP_COUNT` | no | `5` | Kept rotated files (`app.log.1` …) |
| `LOG_LEVEL` | no | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `LOGSTASH_URL` | no | empty | Authenticated HTTPS endpoint for remote ELK logging |
| `LOGSTASH_USERNAME` | no | empty | Logstash HTTP Basic Auth user; set with URL and password |
| `LOGSTASH_PASSWORD` | no | empty | Logstash HTTP Basic Auth password; set with URL and username |
| `LOG_SERVICE` | no | `socialism-backend` | Service name attached to remote log events |
| `LOG_ENVIRONMENT` | no | `local` | Environment attached to remote log events |
| `LOGSTASH_TIMEOUT_SECONDS` | no | `10` | Per-event remote delivery timeout in the background worker |
| `LOGSTASH_QUEUE_SIZE` | no | `512` | Maximum queued remote log events before new events are dropped loudly |
| `BOLAGSAPI_API_KEY` | for DD company tools | — | When set, company tools use BolagsAPI MCP. When empty, the same tools scrape Allabolag.se |
| `BOLAGSAPI_MCP_URL` | no | `https://mcp.bolagsapi.se/mcp` | BolagsAPI remote MCP |
| `BOLAGSAPI_CACHE_DIR` | no | `data/bolagsapi_cache` | Disk cache for MCP tool results. Entries expire after 10 months |
| `LAGEN_NU_OFFICIAL_MCP_URL` | no | `https://lagen.nu/mcp` | Official lagen.nu MCP for the generic research provider. Empty is a hard error (no mock) |
| `LAGEN_NU_OFFICIAL_MCP_TIMEOUT_SECONDS` | no | `20` | Timeout for official lagen.nu MCP calls |
| `RESEARCH_KNOWLEDGE_LOOKUP_LIMIT` | no | `10` | Max Question→Evidence graph hits per need (1–32) |
| `RESEARCH_KNOWLEDGE_FRESHNESS_MAX_AGE_SECONDS` | no | unset | Age after which reused graph evidence is stale. Unset = freshness unknown; providers still run |
| `SUPABASE_URL` | **yes** | — | Supabase project URL (Auth + Admin invite) |
| `SUPABASE_SERVICE_ROLE_KEY` | **yes** | — | Backend-only; Admin invite API and Storage Vector Buckets (never ship to the SPA) |
| `SUPABASE_VECTOR_BUCKET` | no | `research-knowledge` | Storage Vector Bucket in the Socialism project |
| `SUPABASE_VECTOR_INDEX` | no | `documents-openai` | Vector index inside the research bucket |
| `SUPABASE_VECTOR_DISTANCE_METRIC` | no | `cosine` | Immutable index metric: `cosine` or `euclidean` |
| `ALLOW_LOCAL_LOGIN` | no | `false` | Local only. Enables `POST /auth/local-login` (used by `/dev-in`). **Never set in production.** |
| `LOCAL_AUTH_JWT_SECRET` | with local login | — | Long random secret for local-only tokens; never used for Supabase Magic Link tokens |
| `SUPABASE_S3_ACCESS_KEY_ID` | for Storage | — | S3 access key from Dashboard → Storage → S3. Required to upload annual reports or persist report artifacts |
| `SUPABASE_S3_SECRET_ACCESS_KEY` | for Storage | — | Matching S3 secret. Backend only |
| `SUPABASE_S3_REGION` | for Storage | — | Project region shown on the Storage S3 page |

`.env` example:

```env
DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:PASSWORD@HOST:5432/postgres
MIGRATION_DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:PASSWORD@HOST:5432/postgres
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

LLM_PROVIDER=cerebras
LLM_REASONING_EFFORT=medium
LLM_MAX_TOKENS=8192
LLM_TIMEOUT_SECONDS=60
DOCUMENT_KNOWLEDGE_LLM_MAX_TOKENS=8192
DOCUMENT_KNOWLEDGE_LLM_TIMEOUT_SECONDS=180
CEREBRAS_API_KEY=csk-...
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=sk-...
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_TIMEOUT_SECONDS=60
PERSONA_GENERATOR=deepseek
SIMULATION_ENGINE=none
MAX_CONCURRENT_SIMULATION_JOBS=2
LOG_DIR=data/logs
LOG_MAX_BYTES=2000000
LOG_BACKUP_COUNT=5
LOG_LEVEL=INFO
# LOGSTASH_URL=https://socialism-logstash.fly.dev
# LOGSTASH_USERNAME=socialism
# LOGSTASH_PASSWORD=generate-a-long-random-secret
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_VECTOR_BUCKET=research-knowledge
SUPABASE_VECTOR_INDEX=documents-openai
SUPABASE_VECTOR_DISTANCE_METRIC=cosine
SUPABASE_S3_ACCESS_KEY_ID=your-s3-access-key
SUPABASE_S3_SECRET_ACCESS_KEY=your-s3-secret
SUPABASE_S3_REGION=eu-central-1
```

Constraints:

- The selected chat provider key (`CEREBRAS_API_KEY` or `DEEPSEEK_API_KEY`) is required at startup even when `PERSONA_GENERATOR=stub`. There is no keyword/heuristic LLM fallback for chat or reports, and no automatic fallback between providers.
- `OPENAI_API_KEY` is required for Semantic Similarity Rating (report tone/style). The SSR embeddings client reads `settings.openai_api_key` explicitly — not the process env after OASIS mirrors DeepSeek into `OPENAI_API_KEY`.
- `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are required at startup. Magic Link access tokens are verified against the project's public JWKS endpoint; no shared JWT secret is needed. The service role key must never be exposed to the frontend.
- When the research worker is enabled, startup creates the configured Supabase Vector Bucket/index if needed and verifies that its dimension equals `EMBEDDING_DIMENSION`. An existing index with another dimension, metric, or data type stops startup. `GET /health/research-vector` exposes the active bucket, index, and dimension without credentials.
- `ALLOW_LOCAL_LOGIN=true` plus `LOCAL_AUTH_JWT_SECRET=<long-random-value>` unlocks a localhost-only shortcut: open `/dev-in` to sign in as `erik@fremred.se` on the Devbrains kund without a magic-link email. Leave both unset everywhere except a developer machine.
- `SUPABASE_S3_*` are required when storing files (annual reports, generated report HTML). Missing keys fail the upload or report job — there is no disk fallback for new artifacts. See [Supabase setup](supabase-setup.md#storage-s3).
- Settings live only in `app/config.py` — do not call `os.getenv` / `load_dotenv` in app code.
- `BOLAGSAPI_API_KEY` selects the company-data backend: BolagsAPI MCP when set, Allabolag scrape when empty. One path per process — a BolagsAPI failure does not fall through to Allabolag. Successful tool results (and Allabolag HTML) are cached on disk for 10 months.

### Live voice

Expert chat can open a live phone-style session. Audio never hits this API: `POST /personas/{id}/live-token` mints provider credentials; the browser talks PCM to the provider WebSocket. Tools and Mem0 stay on `POST /personas/{id}/live-tool` and `POST /personas/{id}/live-memory`. Expert-only (`kind != "expert"` → 404).

| Variable | Required | Default | Notes |
| -------- | -------- | ------- | ----- |
| `LIVE_VOICE_PROVIDER` | no | `gemini` | `gemini` or `elevenlabs`. No automatic fallback |
| `GOOGLE_API_KEY` | **when `LIVE_VOICE_PROVIDER=gemini`** | empty | Same key as playground Gemini vision. Missing key → 503 on mint |
| `GEMINI_LIVE_MODEL` | no | `gemini-2.5-flash-native-audio-latest` | Constrained Gemini Live model |
| `GEMINI_LIVE_VOICE` | no | `Algenib` | Prebuilt Gemini voice |
| `ELEVENLABS_API_KEY` | **when `LIVE_VOICE_PROVIDER=elevenlabs`** | empty | Server-only. Missing key/agent/voice → 503 on mint |
| `ELEVENLABS_AGENT_ID` | **when `LIVE_VOICE_PROVIDER=elevenlabs`** | empty | One private shell agent; prompt/`first_message` are overridden per call |
| `ELEVENLABS_VOICE_ID` | **when `LIVE_VOICE_PROVIDER=elevenlabs`** | empty | TTS voice override. Enable voice overrides on the agent Security tab |
| `ELEVENLABS_TOOL_IDS` | no | empty | JSON object mapping OpenAI tool names to ElevenLabs client tool ids. When set, every allowlisted expert tool must have an id (fail loud). Client tools must already exist on the agent (`expects_response: true`). When unset, v1 still executes `client_tool_call` via `/live-tool` (backend rejects disallowed names) |
| `ELEVENLABS_BASE_URL` | no | `https://api.elevenlabs.io` | |
| `ELEVENLABS_SIGNED_URL_TTL_SECONDS` | no | `900` | Conservative `expires_at` on the session payload |

Enable ElevenLabs: set `LIVE_VOICE_PROVIDER=elevenlabs` plus `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, and `ELEVENLABS_VOICE_ID`, then restart the backend. Gemini remains the path when `LIVE_VOICE_PROVIDER=gemini` (and `GOOGLE_API_KEY` is set). Do not add an ElevenLabs SDK — the frontend speaks the WebSocket protocol directly.

On the ElevenLabs agent, enable Security overrides for system prompt, first message, voice, and (if using `ELEVENLABS_TOOL_IDS`) tools.

HTTP access lines and uncaught ASGI exceptions (DeepSeek timeouts, tracebacks) go to **stdout** and to `backend/data/logs/app.log`. When the file hits `LOG_MAX_BYTES` it becomes `app.log.1` and a new `app.log` starts (`LOG_BACKUP_COUNT` files kept). Körning-loggar under `data/oasis/…` are separate.

## Optional: OASIS simulation

Default `SIMULATION_ENGINE=none` flips run status via a background job with an empty results attempt (fast local loop).

For live multi-agent sims:

```bash
cd backend
uv sync --extra oasis   # heavy: CAMEL + torch
# set SIMULATION_ENGINE=oasis in .env
```

Then `POST /runs/{id}/start` queues `run_simulate` and runs the full population + injectors across all configured ticks. Per-run `oasis_options.platform` selects `twitter` (default) or `reddit`.

Adapter layers, phased decoupling from camel-oasis internals, and an upgrade checklist: [simulation-engine-layers.md](simulation-engine-layers.md). Product-module dispatch (`report_modes`, no politik fallback): [module-registry.md](module-registry.md).

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

### Refresh SCB persona name catalog (one-off)

Age-weighted first names and the surname pool come from checked-in static data
(`app/services/persona_catalog_scb_names.py`). Re-import manually when SCB tables
change — persona generation never calls SCB at runtime.

```bash
cd backend
# from repo root:
PYTHONPATH=backend:. python3 backend/scripts/import_scb_names.py
```

Uses PxWebApi v2 tables `TAB615` (first names by birth year) and `TAB616` (top surnames).

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

From the repo root, `make backend` and `make start` enable `--reload` by default. Pass `RELOAD=0` to keep a single backend process (`make backend RELOAD=0`, `make start RELOAD=0`).

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

Uses in-memory SQLite; no network required. Tests set dummy chat-provider keys and mock the LLM client. GitHub Actions runs this on every PR and on push to `main` (see [ci.md](ci.md)). Smoke (`-m smoke`) stays opt-in.

## Troubleshooting

| Symptom | Likely cause |
| ------- | ------------ |
| App exits immediately on boot | Missing/empty selected chat key (`CEREBRAS_API_KEY` or `DEEPSEEK_API_KEY`) |
| CORS errors from Vite | `ALLOWED_ORIGINS` missing the browser origin |
| Start returns 400 about OASIS | `SIMULATION_ENGINE=oasis` without `uv sync --extra oasis` or without DeepSeek key mirroring |
| Start returns 400 about missing message | Injection `message_id` not in budskapsbibliotek — fix before start (bodies are frozen then) |
| Post-hoc interview 409 / tick errors | Run still simulating, or `through_tick_index` out of range — see [interview runbook](runs-interviews-and-quality.md) |
| Benchmark exits about API key | Missing/placeholder `DEEPSEEK_API_KEY` in `backend/.env` |
| Benchmark `OasisUnavailable` | Run `uv sync --extra oasis`; confirm camel-oasis import works |
| Benchmark JSON ok but UI unchanged | Script does not persist attempts — check `data/benchmark_*.json`, not the körning detail page |
| Jobs stuck after crash | Restart API — interrupted jobs are failed on lifespan startup |
| Report job hangs | Raise/check `LLM_TIMEOUT_SECONDS`; confirm the selected chat provider is reachable |
| SQLite alter migration fails | Ensure `render_as_batch=True` and review autogenerated revision |
| `EMAXCONNSESSION` / max clients 15 | Session-mode pooler is full. Restart with `make start RELOAD=0` so leftover uvicorn `--reload` sessions drop; SQLAlchemy and Mem0 pools are capped below 15. |

## Supabase Postgres migration

For a new empty Supabase database:

1. Pause all writers to the SQLite database and make a filesystem copy of the source file.
2. Set `DATABASE_URL` to the direct/session Supabase URL, not the transaction pooler.
3. Run `uv run alembic upgrade head` to create the target schema.
4. Run `uv run python scripts/migrate_sqlite_to_postgres.py --source sqlite:///./data/opinionssimulator.db --replace-target`. Alembic creates some catalog rows, so the explicit flag clears all application tables in this dedicated new target before copying. The importer then copies in foreign-key order, resets integer sequences, and verifies row counts plus primary keys before committing. Without the flag it refuses any non-empty target.
5. Start the local backend against Postgres and exercise login, Expertgranskning, research, reports and background jobs.
6. Keep the SQLite snapshot read-only until the Postgres backup has been verified. When a deployment target is selected, configure the same `DATABASE_URL` there and repeat the verification before calling it production.

Never paste the database password into git, logs, screenshots or a frontend environment. Alembic remains authoritative; do not edit the application schema in the Supabase dashboard.

See [supabase-setup.md](supabase-setup.md).

### LibreOffice (Word underlag)

Uploading a `.docx` underlag converts it to PDF with LibreOffice (`soffice --headless`). Install LibreOffice locally and set `LIBREOFFICE_BIN` if the binary is not on `PATH`.

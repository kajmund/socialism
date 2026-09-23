# Socialism

Internal tool for testing political messaging (A/B or stimulus/control) against AI agent populations grounded in local civic context. Swedish UI.

## What you can do

1. Build or compose a **population** (demographic mix of personas)
2. Manage a **persona library** (biography, tone, local context, chat, anecdotes)
3. Edit a **budskapsbibliotek** and configure a **körning** (timeline, branch, OASIS options)
4. Start simulations via background jobs; inspect results and **HTML reports**
5. Browse admin surfaces: Personas, Populationer, Körningar, Budskap, Grunddata, Jobb

Admin CRUD is API-backed by Supabase Postgres. Simulation start defaults to status-only; live multi-agent (OASIS) is optional. Authentication uses Supabase Magic Link.

## Stack

| Layer | Choice |
| ----- | ------ |
| Backend | Python 3.12+ · FastAPI · SQLAlchemy · Alembic |
| Frontend | Vite · React · TypeScript · Tailwind · shadcn |
| Persistent database | Supabase Postgres (`psycopg`) |
| Local/test database | SQLite (`aiosqlite`) |
| Auth | Supabase Auth (email) |
| LLM | Cerebras by default; DeepSeek for A/B; stub persona sampling in tests |
| Runtime | Local only; no deployment target selected |

## Deployment status

The frontend and backend currently run only on a developer machine. There is no hosted application environment or hosting project associated with this repository. Supabase and optional integrations can still be remote services configured through local environment variables. Select and document a hosting target before treating any environment as production.

## Repo layout

```text
socialism/
├── AGENTS.md          # conventions for coding agents
├── Makefile           # make start | backend | frontend | install | test | knowledge-validate
├── .github/workflows/ # CI on PR and push to main
├── okf.project.yaml   # OKF project (end-user manuals)
├── data/              # local corpus helpers
├── docs/              # developer brief, setup guides, architecture
├── knowledge/manual/  # OKF end-user guides (Swedish UI)
├── backend/           # FastAPI admin API
├── frontend/          # React SPA
└── word-addin/        # Word desktop task pane
```

## Prerequisites

| Tool | Version | Used for |
| ---- | ------- | -------- |
| [Python](https://www.python.org/downloads/) | 3.12+ | Backend |
| [uv](https://docs.astral.sh/uv/) | latest | Backend deps |
| [Node.js](https://nodejs.org/) | 20+ | Frontend |
| [pnpm](https://pnpm.io/) | latest | Frontend packages |
| [flyctl](https://fly.io/docs/flyctl/install/) | latest | Local proxy to the Fly-hosted ELK stack |

## Quick start

```bash
# 1) Install deps
make install

# 2) Backend env + DB
cd backend
cp .env.example .env          # CEREBRAS_API_KEY (or DEEPSEEK) + OPENAI_API_KEY required at startup
uv run alembic upgrade head
uv run python -m app.seed
cd ..

# 3) Frontend env
cd frontend
cp .env.example .env          # VITE_API_BASE_URL + Supabase placeholders
cd ..

# 4) Authenticate to Fly once
flyctl auth login

# 5) Run Elasticsearch (:19200), Kibana (:5601), API (:8000), and Vite (:5173)
make start
```

Open [http://localhost:5173/login](http://localhost:5173/login) for Supabase magic-link sign-in. For the local shortcut, set `ALLOW_LOCAL_LOGIN=true` and `LOCAL_AUTH_JWT_SECRET` in `backend/.env`, restart the backend, and open [http://localhost:5173/dev-in](http://localhost:5173/dev-in). API docs: [http://localhost:8000/docs](http://localhost:8000/docs). Kibana: [http://127.0.0.1:5601](http://127.0.0.1:5601).

`make start` fails clearly if Fly authentication is missing, a proxy cannot connect, or Elasticsearch/Kibana does not become healthy. The proxies only listen on `127.0.0.1`. Start them separately with `make elk-proxy` and `make kibana-proxy`.

Or start application services separately: `make backend` / `make frontend` / `make word-addin`. Pass `RELOAD=0` to run the backend without uvicorn `--reload` (`make start RELOAD=0` or `make backend RELOAD=0`). Word add-in sideload: [docs/guides/word-addin.md](docs/guides/word-addin.md).

## Frontend

Admin UI uses the Devbrains charcoal + gold theme (`/runs`, `/personas`, `/populations`, `/messages`, `/config`, `/jobs`, `/reports/:id`). Pages call the API via `VITE_API_BASE_URL`.

```bash
cd frontend
pnpm install
pnpm dev
```

Checks: `pnpm exec tsc -p tsconfig.app.json --noEmit` and `pnpm lint`.

## Backend

Local admin API: personas, populations, runs, messages, catalog, jobs, reports. The frontend uses Supabase magic-link auth, with an explicitly enabled localhost-only shortcut for development.

```bash
cd backend
uv sync
cp .env.example .env
uv run alembic upgrade head
uv run python -m app.seed
uv run uvicorn app.main:app --reload
```

Useful env knobs (see `backend/.env.example`):

- `CEREBRAS_API_KEY` — **required** at startup when `LLM_PROVIDER=cerebras` (default; no silent LLM fallback)
- `DEEPSEEK_API_KEY` — required when `LLM_PROVIDER=deepseek`, and for OASIS
- `OPENAI_API_KEY` — **required** at startup (embeddings for SSR reports)
- `PERSONA_GENERATOR=deepseek|stub` — chat LLM vs offline persona sampling (selected provider key still required)
- `SIMULATION_ENGINE=none|oasis` — empty attempt vs optional OASIS spike (`uv sync --extra oasis`)

OASIS model comparison (after `uv sync --extra oasis`):  
`uv run python scripts/benchmark_simulation_models.py --run-id N` — see [docs/guides/backend-setup.md](docs/guides/backend-setup.md#benchmark-deepseek-models).

Tests: `make test` (backend `pytest` + frontend lint/vitest). CI runs the same suite on every pull request and on push to `main` — see [docs/guides/ci.md](docs/guides/ci.md). A PR must not merge while the **CI** check is red.

## Docs

| Doc | Purpose |
| --- | ------- |
| [knowledge/manual/](knowledge/manual/) | End-user OKF guides (Swedish UI) |
| [knowledge/README.md](knowledge/README.md) | OKF bundle conventions + validate/MCP |
| [docs/client-brief.md](docs/client-brief.md) | Product brief |
| [docs/guides/ci.md](docs/guides/ci.md) | GitHub Actions tests + merge gate |
| [docs/guides/backend-setup.md](docs/guides/backend-setup.md) | Backend setup, jobs, OASIS, troubleshooting |
| [docs/guides/frontend-setup.md](docs/guides/frontend-setup.md) | Frontend setup, routes, env |
| [docs/guides/runs-interviews-and-quality.md](docs/guides/runs-interviews-and-quality.md) | Interviews, branches, quality warnings |
| [docs/guides/supabase-setup.md](docs/guides/supabase-setup.md) | Supabase database, Auth and Storage setup |
| [docs/architecture.md](docs/architecture.md) | Current system architecture |
| [AGENTS.md](AGENTS.md) | Agent / contributor conventions |

Validate OKF manuals: `make knowledge-validate`.

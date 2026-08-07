# Opinionssimulator

Internal tool for testing political messaging (A/B or stimulus/control) against AI agent populations grounded in local civic context. Swedish UI. Pilot: Norrköping 2026.

## What you can do

1. Build or compose a **population** (demographic mix of personas)
2. Manage a **persona library** (biography, tone, local context, chat, anecdotes)
3. Edit a **budskapsbibliotek** and configure a **körning** (timeline, branch, OASIS options)
4. Start simulations via background jobs; inspect results and **HTML reports**
5. Browse admin surfaces: Personas, Populationer, Körningar, Budskap, Grunddata, Jobb

Phase 1: admin CRUD is API-backed (SQLite). Simulation start defaults to status-only; live multi-agent (OASIS) is optional. Auth and Supabase Postgres come later.

## Stack

| Layer | Choice |
| ----- | ------ |
| Backend | Python 3.12+ · FastAPI · SQLAlchemy · Alembic |
| Frontend | Vite · React · TypeScript · Tailwind · shadcn |
| Database (phase 1) | SQLite (`aiosqlite`) under `backend/data/` |
| Database (later) | Supabase Postgres |
| Auth (later) | Supabase Auth (email) |
| LLM | DeepSeek (OpenAI-compatible SDK; stub persona sampling for tests) |
| Hosting | Railway |

## Repo layout

```text
socialism/
├── AGENTS.md          # conventions for coding agents
├── Makefile           # make start | backend | frontend | install | knowledge-validate
├── okf.project.yaml   # OKF project (end-user manuals)
├── data/              # local corpus helpers
├── docs/              # developer brief, setup guides, architecture
├── knowledge/manual/  # OKF end-user guides (Swedish UI)
├── backend/           # FastAPI admin API
└── frontend/          # React SPA
```

## Prerequisites

| Tool | Version | Used for |
| ---- | ------- | -------- |
| [Python](https://www.python.org/downloads/) | 3.12+ | Backend |
| [uv](https://docs.astral.sh/uv/) | latest | Backend deps |
| [Node.js](https://nodejs.org/) | 20+ | Frontend |
| [pnpm](https://pnpm.io/) | latest | Frontend packages |

## Quick start

```bash
# 1) Install deps
make install

# 2) Backend env + DB
cd backend
cp .env.example .env          # DEEPSEEK_API_KEY + OPENAI_API_KEY required at startup
uv run alembic upgrade head
uv run python -m app.seed
cd ..

# 3) Frontend env
cd frontend
cp .env.example .env          # VITE_API_BASE_URL + Supabase placeholders
cd ..

# 4) Run both (API :8000, Vite :5173)
make start
```

Open [http://localhost:5173/runs](http://localhost:5173/runs). API docs: [http://localhost:8000/docs](http://localhost:8000/docs).

Or start services separately: `make backend` / `make frontend`.

## Frontend

Admin UI uses the Devbrains charcoal + gold theme (`/runs`, `/personas`, `/populations`, `/messages`, `/config`, `/jobs`, `/reports/:id`). Pages call the API via `VITE_API_BASE_URL`.

```bash
cd frontend
pnpm install
pnpm dev
```

Checks: `pnpm exec tsc -p tsconfig.app.json --noEmit` and `pnpm lint`.

## Backend

Local admin API: personas, populations, runs, messages, catalog, jobs, reports. No auth in phase 1.

```bash
cd backend
uv sync
cp .env.example .env
uv run alembic upgrade head
uv run python -m app.seed
uv run uvicorn app.main:app --reload
```

Useful env knobs (see `backend/.env.example`):

- `DEEPSEEK_API_KEY` — **required** at startup (no silent LLM fallback)
- `OPENAI_API_KEY` — **required** at startup (embeddings for SSR reports)
- `PERSONA_GENERATOR=deepseek|stub` — DeepSeek vs offline persona sampling (key still required)
- `SIMULATION_ENGINE=none|oasis` — empty attempt vs optional OASIS spike (`uv sync --extra oasis`)

OASIS model comparison (after `uv sync --extra oasis`):  
`uv run python scripts/benchmark_simulation_models.py --run-id N` — see [docs/guides/backend-setup.md](docs/guides/backend-setup.md#benchmark-deepseek-models).

Tests: `cd backend && uv run pytest`.

## Docs

| Doc | Purpose |
| --- | ------- |
| [knowledge/manual/](knowledge/manual/) | End-user OKF guides (Swedish UI) |
| [knowledge/README.md](knowledge/README.md) | OKF bundle conventions + validate/MCP |
| [docs/client-brief.md](docs/client-brief.md) | Product brief |
| [docs/guides/backend-setup.md](docs/guides/backend-setup.md) | Backend setup, jobs, OASIS, troubleshooting |
| [docs/guides/frontend-setup.md](docs/guides/frontend-setup.md) | Frontend setup, routes, env |
| [docs/guides/runs-interviews-and-quality.md](docs/guides/runs-interviews-and-quality.md) | Interviews, branches, quality warnings |
| [docs/guides/supabase-setup.md](docs/guides/supabase-setup.md) | Future Supabase migration notes |
| [docs/architecture.md](docs/architecture.md) | Current system architecture |
| [AGENTS.md](AGENTS.md) | Agent / contributor conventions |

Validate OKF manuals: `make knowledge-validate`.

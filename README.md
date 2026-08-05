# Opinionssimulator

Internal tool for testing political messaging (A/B) against AI agent populations grounded in local civic context. Swedish UI. Pilot: Norrköping 2026.

## What you can do

1. Build or compose a **population** (demographic mix of personas)
2. Manage a **persona library** (biography, tone, local context)
3. Configure a **körning** (budskap A/B, scenario, timeline)
4. Browse admin surfaces for Personas / Populationer / Körningar
5. Walk the paper **simulator** demo wizard (`/simulator`)

Phase 1: admin CRUD is API-backed (SQLite). Simulation start defaults to status-only; live multi-agent (OASIS) is optional. Auth and Supabase Postgres come later.

## Stack

| Layer | Choice |
| ----- | ------ |
| Backend | Python 3.12+ · FastAPI · SQLAlchemy · Alembic |
| Frontend | Vite · React · TypeScript · Tailwind · shadcn |
| Database (phase 1) | SQLite (`aiosqlite`) under `backend/data/` |
| Database (later) | Supabase Postgres |
| Auth (later) | Supabase Auth (email) |
| LLM | DeepSeek (OpenAI-compatible SDK; stub mode offline) |
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
cp .env.example .env          # set DEEPSEEK_API_KEY or PERSONA_GENERATOR=stub
uv run alembic upgrade head
uv run python -m app.seed
cd ..

# 3) Frontend env
cd frontend
cp .env.example .env          # VITE_API_BASE_URL=http://localhost:8000
cd ..

# 4) Run both (API :8000, Vite :5173)
make start
```

Open [http://localhost:5173/runs](http://localhost:5173/runs). API docs: [http://localhost:8000/docs](http://localhost:8000/docs).

Or start services separately: `make backend` / `make frontend`.

## Frontend

Dual visual system (do not collapse them):

| Area | Theme | Routes |
| ---- | ----- | ------ |
| Admin | Devbrains charcoal + gold | `/runs`, `/personas`, `/populations` |
| Simulator | Paper / editorial | `/simulator` |

Admin pages call the API via `VITE_API_BASE_URL`. The simulator wizard still uses mock data unless you open a run that has OASIS results.

```bash
cd frontend
pnpm install
pnpm dev
```

Checks: `pnpm exec tsc -p tsconfig.app.json --noEmit` and `pnpm lint`.

Source mockup: `frontend/mockup/Socialism.zip`.

## Backend

Local admin API: personas, populations (recipe + members), runs (timeline JSON). No auth in phase 1.

```bash
cd backend
uv sync
cp .env.example .env
uv run alembic upgrade head
uv run python -m app.seed
uv run uvicorn app.main:app --reload
```

Useful env knobs (see `backend/.env.example`):

- `PERSONA_GENERATOR=deepseek|stub` — offline stub vs DeepSeek
- `SIMULATION_ENGINE=none|oasis` — status flip vs optional OASIS spike (`uv sync --extra oasis`)

Tests: `cd backend && uv run pytest`.

## Docs

| Doc | Purpose |
| --- | ------- |
| [knowledge/manual/](knowledge/manual/) | End-user OKF guides (Swedish UI) |
| [knowledge/README.md](knowledge/README.md) | OKF bundle conventions + validate/MCP |
| [docs/client-brief.md](docs/client-brief.md) | Product brief |
| [docs/guides/backend-setup.md](docs/guides/backend-setup.md) | Backend setup detail |
| [docs/guides/frontend-setup.md](docs/guides/frontend-setup.md) | Frontend setup detail |
| [docs/architecture.md](docs/architecture.md) | Architecture notes |
| [AGENTS.md](AGENTS.md) | Agent / contributor conventions |

Validate OKF manuals: `make knowledge-validate`.

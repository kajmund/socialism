# Opinionssimulator

Internal tool for testing political messaging (A/B) against AI agent populations grounded in local context. Swedish UI. Pilot context: Norrköping 2026.

## Stack

| Layer              | Choice                                               |
| ------------------ | ---------------------------------------------------- |
| Backend            | Python + FastAPI                                     |
| Frontend           | Vite + React SPA + TypeScript                        |
| Database (phase 1) | SQLite (`aiosqlite`) via SQLAlchemy + Alembic        |
| Database (later)   | Supabase Postgres                                    |
| Auth (later)       | Supabase Auth (email only)                           |
| Hosting            | Railway                                              |
| LLM + embeddings   | OpenAI (later)                                       |

## Repo layout

```text
socialism/
├── AGENTS.md
├── README.md
├── data/
├── docs/
├── backend/
└── frontend/
```

## Frontend

Dual visual system:

- **Simulator** (`/simulator`) — paper/editorial 5-step wizard from the mockup
- **Admin** (Personas / Populationer / Körningar) — Devbrains charcoal + gold (API-backed)

```bash
cd frontend
pnpm install
cp .env.example .env   # then edit if needed
pnpm dev
```

Checks: `pnpm tsc --noEmit` and `pnpm lint`.

Source mockup: `frontend/mockup/Socialism.zip`.

## Prerequisites

| Tool | Version | Used for |
| ---- | ------- | -------- |
| [Python](https://www.python.org/downloads/) | 3.12+ | Backend |
| [uv](https://docs.astral.sh/uv/) | latest | Backend deps |
| [Node.js](https://nodejs.org/) | 20+ | Frontend |
| [pnpm](https://pnpm.io/) | latest | Frontend packages |

## Backend

Local SQLite admin API (personas, populations, runs). See [docs/guides/backend-setup.md](docs/guides/backend-setup.md).

```bash
cd backend
uv sync
cp .env.example .env
uv run alembic upgrade head
uv run python -m app.seed
uv run uvicorn app.main:app --reload
```

Frontend still uses mock data for `/simulator`. Admin pages call the API at `VITE_API_BASE_URL`. Supabase comes in a later phase.

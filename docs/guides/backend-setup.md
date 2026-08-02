# Backend setup

This project uses a separate Python + FastAPI backend for the Opinionssimulator admin API (personas, populations, runs). The frontend talks to it over JSON via `VITE_API_BASE_URL`.

## Phase 1: SQLite

Local development uses SQLite (`aiosqlite`) so you can run without Supabase. SQLAlchemy models + Alembic migrations are written to stay portable — later we swap `DATABASE_URL` to Supabase Postgres.

## Init

```bash
cd backend
uv sync
cp .env.example .env
```

`.env` typically:

```env
DATABASE_URL=sqlite+aiosqlite:///./data/opinionssimulator.db
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# LLM (persona generation + interview chat) — DeepSeek
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
PERSONA_GENERATOR=deepseek
```

Set `PERSONA_GENERATOR=stub` (or leave `DEEPSEEK_API_KEY` empty with stub) for offline generation without calling DeepSeek. Interview chat also falls back to a short stub reply in stub mode.

## Database migrations

Alembic owns schema changes. Initialize is already done; after model changes:

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

API docs: http://localhost:8000/docs  
Health: http://localhost:8000/health

## Imports (`from app...`)

`backend/app` is installed as an editable package by `uv sync`, so `from app...` imports work from uvicorn, tests, and scripts.

## Tests

```bash
cd backend
uv run pytest
```

Uses in-memory SQLite; no network required.

## Later: Supabase Postgres

When moving off SQLite:

1. Point `DATABASE_URL` at the direct Supabase Postgres URL (session mode, not the transaction pooler).
2. Add `psycopg` (and later Auth / OpenAI as needed).
3. Re-run `alembic upgrade head` against Postgres.
4. Do not treat the Supabase dashboard as the schema source of truth — Alembic remains authoritative.

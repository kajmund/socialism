# Backend — agent notes

This is the FastAPI service for **Opinionssimulator**. Read [../AGENTS.md](../AGENTS.md) first — universal building rules live there. This file adds backend-specific conventions.

## Stack

- Python 3.12+
- FastAPI + uvicorn
- Pydantic v2 + pydantic-settings
- `httpx` for outbound HTTP
- `pytest` for tests
- SQLAlchemy models + Alembic migrations for database schema changes
- **Phase 1 DB:** SQLite via `aiosqlite` (local file under `backend/data/`)
- **Later:** Supabase Postgres + Auth (not wired yet)
- **LLM:** DeepSeek via OpenAI-compatible SDK (`app/llm/`)
- `structlog` for logging
- `uv` for dependency + project management

## Dependency policy

See universal policy in [../AGENTS.md](../AGENTS.md). Backend-specific:

- **Prefer stdlib:** `pathlib`, `datetime`, `uuid`, `enum`, `dataclasses`, `asyncio`, `collections`, `itertools`, `json`, `urllib`.
- **Not OK without justification:** `python-dateutil`, `toolz`, `funcy`, `more-itertools`, small JSON/string micro-libs, "ergonomic" wrappers on top of declared SDKs.
- Dev deps (test/lint/build) have a looser bar but still pick widely-used, low-footprint tools (`pytest`, `ruff`, `httpx`).

## Layout

```text
backend/
├── alembic/
│   ├── env.py           # Imports app database metadata for autogenerate
│   └── versions/        # Reviewed migration files
├── alembic.ini
├── app/
│   ├── main.py          # FastAPI entrypoint
│   ├── config.py        # Pydantic settings — single source of truth for env
│   ├── api/             # FastAPI routers (personas, populations, runs, messages, health)
│   ├── database/        # SQLAlchemy models, async session, base
│   ├── llm/             # DeepSeek client, persona gen, interview chat
│   ├── locality/        # Norrköping brief for grounded prompts
│   ├── schemas/         # Pydantic request/response models
│   ├── services/        # Population generate, OASIS körning spike, catalogs
│   └── seed.py          # Load demo data into SQLite
├── tests/
└── pyproject.toml
```

Optional dependency extra `oasis` (`camel-oasis`) — not installed by default (`uv sync --extra oasis`). That install is heavy (CAMEL + torch). On Python 3.13, `pyproject.toml` overrides pin conflicts (`openai`, `tiktoken`, `pillow`, pytest).
## Code style (backend-specific)

- **Type hints on public functions and module-level things.** Don't annotate every local.
- **Async by default in request-path code.** Don't run blocking I/O on the event loop. Tempfile + small synchronous file reads are OK (they're fast); network calls must be async.
- **Use `async def` for all route handlers** and any I/O service function.
- **Validate at boundaries only.** HTTP input is validated by Pydantic models. External API responses are validated when parsed. Internal callers are trusted.

## Configuration

- `app.config.settings` is the single source of truth. Import settings where needed; never call `os.getenv` in app code, never call `load_dotenv`.
- If a third-party SDK reads `os.environ` directly, add the mirror in `config.py` — don't sprinkle `setdefault` elsewhere.
- Fail fast on startup when required env vars are missing.

## Database

- Alembic is the source of truth for schema changes.
- Phase 1 uses SQLite (`DATABASE_URL=sqlite+aiosqlite:///./data/opinionssimulator.db`). Models stay dialect-portable so we can point at Supabase Postgres later.
- Run migrations from `backend/` with `uv run alembic upgrade head`.
- Seed demo data with `uv run python -m app.seed`.

## Domain (admin library)

CRUD for personas, populations (members + recipe/fingerprint), and runs (timeline JSON). No auth.

**Simulation:** `POST /runs/{id}/start` queues a `run_simulate` background job (202) and sets the run to `running`. With an A/B branch, the worker simulates Version A and B separately (shared stem ticks through `afterIndex` + each branch). Results are stored as `results.attempts[]` (newest first); each attempt has `variants[]`. Re-runs append attempts instead of overwriting. Default `SIMULATION_ENGINE=none` finishes quickly with empty variant payloads. Optional OASIS (`SIMULATION_ENGINE=oasis`) runs capped multi-agent sims via `camel-oasis`. Install with `uv sync --extra oasis`. Caps: `OASIS_MAX_AGENTS`, `OASIS_MAX_TICKS`. CLI: `uv run python -m app.services.oasis_run --run-id N`.

## Tests

- **Prefer unit over integration.** Mock at the service boundary.
- Fast suite uses in-memory SQLite and must stay green with no network.
- Integration tests (when added) go behind `@pytest.mark.integration`.
- Tests live under `tests/` mirroring the area under test.
- Profile CSV mapping for OASIS is unit-tested without importing `camel-oasis`.

## Anti-patterns (rejected)

- `os.getenv` / `load_dotenv` in modules.
- Wrapping FastAPI responses in custom envelope classes.
- Over-catching `Exception` just to log and re-raise; let it propagate.
- Shared state through globals instead of FastAPI `app.state` or DI.
- Silent fallbacks that hide real config errors.

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
│   ├── modules/         # Product-module manifests + registry (dd, politik)
│   ├── api/             # Routers: personas, populations, runs, messages, configurations, catalog, jobs, reports, playground, health, ws
│   ├── database/        # SQLAlchemy models, async session, base
│   ├── llm/             # DeepSeek client, persona gen, interview chat
│   ├── schemas/         # Pydantic request/response models
│   ├── services/        # Population generate, OASIS körning spike, catalogs
│   └── seed.py          # Load demo data into SQLite
├── scripts/             # Operator/dev CLIs (e.g. model benchmark)
├── tests/
└── pyproject.toml
```

Optional dependency extra `oasis` (`camel-oasis`) — not installed by default (`uv sync --extra oasis`). That install is heavy (CAMEL + torch). On Python 3.13, `pyproject.toml` overrides pin conflicts (`openai`, `tiktoken`, `pillow`, pytest).

**Model benchmark:** `uv run python scripts/benchmark_simulation_models.py --run-id N` runs the same körning under each `--models` id (default reasoner vs chat), prints wall time + activity metrics, and writes JSON under `data/`. **Prompt benchmark:** `uv run python scripts/benchmark_prompt_configurations.py --run-id N` compares engagement balance across `oasis.agents.action_rules` variants on dedicated Configuration rows; see [docs/guides/backend-setup.md](../docs/guides/backend-setup.md#benchmark-prompt-configurations-engagement-balance). Neither benchmark script commits `run.results` (unlike `python -m app.services.oasis_run`).

## Code style (backend-specific)

- **Type hints on public functions and module-level things.** Don't annotate every local.
- **Async by default in request-path code.** Don't run blocking I/O on the event loop. Tempfile + small synchronous file reads are OK (they're fast); network calls must be async.
- **Use `async def` for all route handlers** and any I/O service function.
- **Validate at boundaries only.** HTTP input is validated by Pydantic models. External API responses are validated when parsed. Internal callers are trusted.

## Configuration

- `app.config.settings` is the single source of truth. Import settings where needed; never call `os.getenv` in app code, never call `load_dotenv`.
- If a third-party SDK reads `os.environ` directly, add the mirror in `config.py` — don't sprinkle `setdefault` elsewhere.
- Fail fast on startup when required env vars are missing.

## Prompts (database, not code)

**All LLM prompt text used at runtime must come from the active configuration in the database** — not from hardcoded strings in call sites.

- Load via `require_active_prompts` / `render_prompt` (`app/services/prompt_store.py`, `prompt_catalog.py`). The active configuration’s `prompts` map is the source of truth.
- New prompt keys: add the key + defaults in `PROMPT_FIELDS` (`prompt_catalog.py`) so seed/admin/UI know about them, then ensure the active configuration has the text (seed or Tools → Konfigurationer). Do not invent one-off prompt strings in `app/llm/` or services.
- Defaults in `prompt_catalog.py` exist only as catalog/seed for new configs and missing keys — not as a parallel production path that bypasses the DB.
- Fail loudly if the active configuration or a required prompt key is missing. Do not fall back to a hardcoded Swedish/English prompt body in Python.

## Database

- Alembic is the source of truth for schema changes.
- Phase 1 uses SQLite (`DATABASE_URL=sqlite+aiosqlite:///./data/opinionssimulator.db`). Models stay dialect-portable so we can point at Supabase Postgres later.
- Run migrations from `backend/` with `uv run alembic upgrade head`.
- Seed demo data with `uv run python -m app.seed`.

## Domain (admin library)

CRUD for personas, populations (members + recipe/fingerprint), runs (timeline JSON), and configurations (name + language + prompts map + `ssr_temperature` + `report_thresholds` + scoped grunddata catalog lists; exactly one active globally drives LLM prompts, report SSR temperature, snabbrapport verdict thresholds, and `/catalog`). No auth.

**Simulation:** `POST /runs/{id}/start` queues a `run_simulate` background job (202) and sets the run to `running`. With an A/B branch, the worker simulates Version A and B **concurrently** (shared stem ticks through `afterIndex` + each branch; separate artifact dirs). `branch.mode` is `ab` or `stimulus_control` (labels only on the backend — control ticks must be silent in the payload). Overlapping `run_simulate` jobs are capped by `MAX_CONCURRENT_SIMULATION_JOBS` (default 2); waiting jobs stay `pending` until a slot frees. Start freezes library `message_id` bodies into injection text. Results are stored as `results.attempts[]` (newest first); each attempt has `variants[]` (incl. `quality_warnings` from lexical convergence when OASIS runs). Re-runs append attempts instead of overwriting. Default `SIMULATION_ENGINE=none` finishes quickly with empty variant payloads. Optional OASIS (`SIMULATION_ENGINE=oasis`) runs multi-agent sims via `camel-oasis` with the **full population** plus injectors, and **all configured ticks** (no agent/tick caps). Reaction rounds use **stratified sampling** and **budskag engagement rules** (`oasis_engagement.py` — operator guide `knowledge/manual/reaktionsmodell-i-simulering.md`): not every agent acts every round; passive scroll-by agents skip later rounds on the same injection until the next budskag; `CREATE_COMMENT` requires prior like/dislike on the post or a comment in that thread. A *silent* tick skips new injections but still runs population reaction rounds. Planned tick `interviews[]` run as OASIS `ManualAction(INTERVIEW)` after reaction rounds. Post-hoc interviews use `/runs/.../interview` and persist on `persona_messages` with run-scope columns (separate from library chat). Install with `uv sync --extra oasis`. CLI: `uv run python -m app.services.oasis_run --run-id N`. Population agents get Swedish env prompts (`oasis_swedish.py`) plus action rules in `user_char`: like = stöd, dislike = avstånd, no like+kritisk kommentar. Per-run `oasis_options.platform` (`twitter` default, or `reddit`) selects profile format, agent graph, recsys, and action set; Reddit uses a discrete scenario clock for tick markers. `oasis_options.allow_population_create_post` (default true) gates `CREATE_POST` for the population; injectors always post via `ManualAction`. Optional `oasis_options.enable_search_duckduckgo` / `enable_search_wiki` / `enable_sympy_tools` attach external toolkits (default off; legacy `enable_web_search` expands to both search flags). Twitter actions include repost/quote; Reddit omits those. Variant results include `follows` / `mutes` / `reports` / `trace` / `action_histogram` / `agent_tools` from the OASIS SQLite artifact, plus `log_path` pointing at `data/oasis/run_{id}/attempts/{attempt_id}/{variant}.log`. Developer runbook: [../docs/guides/runs-interviews-and-quality.md](../docs/guides/runs-interviews-and-quality.md).

**Reports:** `POST /reports` with `{ sources: [{ run_id, attempt_id }], title?, locale? }` queues `report_generate` (202). Always snabbrapport (`mode` is always `"quick"` on create; legacy `"full"` rows may still exist). `locale` is `"sv"` (default) or `"en"`. Injection-keyword topics + SSR tone/style (OpenAI embeddings of reaction texts vs anchors) + configurable threshold templates (`report_thresholds` on active configuration) — no DeepSeek narrative. Requires matching-language active configuration for anchors + `ssr_temperature` + `report_thresholds`, and `OPENAI_API_KEY` at startup. Artifacts under `data/reports/{id}/` (`report.html`, `report.slots.json`, `report.ssr.json` including frozen `report_thresholds` snapshot). Fetch via `GET /reports/{id}/html`. **Report HTML visual style** must match the admin/mockup system in `frontend/mockup/extracted/` (Devbrains charcoal + gold) — see root [AGENTS.md](../AGENTS.md) → **Frontend visual system**. OASIS simulation prompts stay Swedish regardless of report locale. Anchor embeddings are write-through cached (memory + `data/embedding_cache/`) by `(embedding_model, statement)` in `app/services/ssr/embeddings.py`; reaction texts are not cached. Admin: `GET/DELETE /embeddings/cache`.

**Playground:** `GET /playground/anchors`, `POST /playground/ssr/rate`, `POST /playground/ssr/compare`, `POST /playground/prompts/run`, `GET /playground/image/models`, `POST /playground/image/react` (multipart: persona + image + optional vision/reaction model picks → vision description, in-character reaction, SSR tone/style) — ephemeral calibration; no persistence. Vision providers: OpenAI (default), optional Google (`GOOGLE_API_KEY`) and Ollama Cloud (`OLLAMA_API_KEY`).

**Message images:** `POST /messages/images/upload` (SHA256 cache + vision caption), `GET/PATCH/DELETE /messages/images/cache[/{sha256}]`, `GET …/file` — disk under `data/image_cache/`. Messages may reference `metadata.image_sha256` with optional body (image-only posts). Run start composes frozen injection text from body + cached caption.

## Tests

- **Prefer unit over integration.** Mock at the service boundary.
- Fast suite uses in-memory SQLite and must stay green with no network.
- Integration tests (when added) go behind `@pytest.mark.integration`.
- Manual OASIS smoke (live camel-oasis + DeepSeek): `@pytest.mark.smoke` under `tests/smoke/`; run with `uv run pytest -m smoke` or `scripts/run_simulation_smoke.py` after `uv sync --extra oasis`. Default pytest excludes smoke (`addopts` in `pyproject.toml`).
- OASIS action vocabulary: single source in `app/services/simulation/action_catalog.py` — see [simulation-engine-layers.md](../docs/guides/simulation-engine-layers.md) for adapter phases and camel-oasis upgrade checklist.
- Tests live under `tests/` mirroring the area under test.
- Profile CSV mapping for OASIS is unit-tested without importing `camel-oasis`.

## Anti-patterns (rejected)

- `os.getenv` / `load_dotenv` in modules.
- Wrapping FastAPI responses in custom envelope classes.
- Over-catching `Exception` just to log and re-raise; let it propagate.
- Shared state through globals instead of FastAPI `app.state` or DI.
- Silent fallbacks that hide real config errors.
- Hardcoding LLM prompt bodies in Python modules instead of the active configuration’s prompts map.

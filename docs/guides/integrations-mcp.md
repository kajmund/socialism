# Integrations (MCP + help chat)

## OKF-backed help

Operator manuals in [`knowledge/manual/`](../knowledge/manual/) are loaded by `integrations/okf/corpus.py`. Both the in-app help chat and the MCP server retrieve relevant guides by keyword overlap and inject them into DeepSeek prompts.

## In-app help chat

- **Frontend:** floating **Hjälp** button on every page (`App.tsx`) → WebSocket scope `help` + `MessengerChat`
- **View injection:** each message sends `{ path, view_key, label, params, search }` from the current route
- **Backend:** `GET/DELETE /help/messages`, `POST /help/chat`, WebSocket `/ws/chat` with `{ scope: "help", session_id, locale, view }`
- **Read sources:** OKF manuals + read-only DB snapshots (`help_read_context.py`) — personas, runs, populations, messages, configurations, anchor sets, reports, jobs
- **SCB tools:** always on (`scb_search_tables`, `scb_get_table_meta`, `scb_query`, `scb_population_dist`)
- **Write policy:** help assistant is read-only; only chat transcript rows are persisted

## MCP server (Cursor)

See [`integrations/README.md`](../integrations/README.md). Stdio server at `integrations/mcp/server.py`:

| Tool | Purpose |
| ---- | ------- |
| `okf_search` | Search manuals |
| `okf_get_guide` | Fetch one guide |
| `ask_help` | DeepSeek answer with OKF context |
| `scb_search_tables` | Search SCB tables (Swedish keywords) |
| `scb_get_table_meta` | Table variables + category codes |
| `scb_query` | Fetch SCB data (JSON-stat2) |
| `list_runs` / `get_run` | Optional API wrappers when `OPINIONSSIMULATOR_API_URL` is set |

Example Cursor config: [`integrations/mcp/cursor-mcp.example.json`](../integrations/mcp/cursor-mcp.example.json).

Run locally: `make knowledge-mcp` (from repo root, after `cd integrations/mcp && uv sync`).

## Env

| Variable | Service | Notes |
| -------- | ------- | ----- |
| `DEEPSEEK_API_KEY` | backend + MCP | Required |
| `OKF_MANUAL_ROOT` | backend + MCP | Optional override; default `knowledge/manual` |
| `OPINIONSSIMULATOR_API_URL` | MCP only | e.g. `http://127.0.0.1:8000` for run tools |

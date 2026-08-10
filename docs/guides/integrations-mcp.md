# Integrations (MCP + help chat)

## OKF-backed help

Operator manuals in [`knowledge/manual/`](../knowledge/manual/) are loaded by `integrations/okf/corpus.py`. Both the in-app help chat and the MCP server retrieve relevant guides by keyword overlap and inject them into DeepSeek prompts.

## In-app help chat

- **Frontend:** floating **Hjälp** button in `AdminShell` → WebSocket scope `help` + `MessengerChat`
- **Backend:** `GET/DELETE /help/messages`, `POST /help/chat`, WebSocket `/ws/chat` with `{ scope: "help", session_id, locale }`
- **Persistence:** `help_messages` table keyed by browser `session_id` (localStorage)
- **Prompt:** `help.system` in Konfigurationer (defaults seeded via prompt catalog)

## MCP server (Cursor)

See [`integrations/README.md`](../integrations/README.md). Stdio server at `integrations/mcp/server.py`:

| Tool | Purpose |
| ---- | ------- |
| `okf_search` | Search manuals |
| `okf_get_guide` | Fetch one guide |
| `ask_help` | DeepSeek answer with OKF context |
| `list_runs` / `get_run` | Optional API wrappers when `OPINIONSSIMULATOR_API_URL` is set |

Example Cursor config: [`integrations/mcp/cursor-mcp.example.json`](../integrations/mcp/cursor-mcp.example.json).

Run locally: `make knowledge-mcp` (from repo root, after `cd integrations/mcp && uv sync`).

## Env

| Variable | Service | Notes |
| -------- | ------- | ----- |
| `DEEPSEEK_API_KEY` | backend + MCP | Required |
| `OKF_MANUAL_ROOT` | backend + MCP | Optional override; default `knowledge/manual` |
| `OPINIONSSIMULATOR_API_URL` | MCP only | e.g. `http://127.0.0.1:8000` for run tools |

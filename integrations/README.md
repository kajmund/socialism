# Integrations

External connectors for Opinionssimulator — MCP servers and shared OKF helpers.

## Layout

```text
integrations/
├── okf/           # OKF manual loader + search (used by MCP and backend help chat)
├── scb/           # SCB PxWebApi 2 client + tools (MCP + in-app help chat)
└── mcp/           # MCP stdio server for Cursor and other MCP clients
```

## OKF corpus

Operator manuals live in [`knowledge/manual/`](../knowledge/manual/). The loader in `integrations/okf/corpus.py` reads those markdown guides (YAML frontmatter + body) and ranks them by keyword overlap for retrieval-augmented help.

Validate manuals: `make knowledge-validate` from the repo root.

## MCP server (Cursor)

The MCP server exposes OKF search/read tools and a DeepSeek-backed `ask_help` tool. Optional tools wrap the FastAPI backend when `OPINIONSSIMULATOR_API_URL` is set.

### Setup

1. Copy [`mcp/cursor-mcp.example.json`](mcp/cursor-mcp.example.json) into your Cursor MCP config (or merge the `opinionssimulator` entry).
2. Set env vars:
   - `DEEPSEEK_API_KEY` — required for `ask_help`
   - `OPINIONSSIMULATOR_API_URL` — optional, e.g. `http://127.0.0.1:8000` for run/persona tools
3. Install MCP server deps once:

```bash
cd integrations/mcp && uv sync
```

4. Restart Cursor so the MCP server starts.

### Tools

| Tool | Description |
| ---- | ----------- |
| `okf_search` | Search operator manuals by query |
| `okf_get_guide` | Fetch one guide by slug (filename without `.md`) |
| `ask_help` | Answer a help question with OKF context + DeepSeek |
| `scb_search_tables` | Search SCB Statistikdatabasen tables (PxWebApi 2) |
| `scb_get_table_meta` | Variable codes/labels for one SCB table |
| `scb_query` | Fetch SCB table data (JSON-stat2) |
| `scb_population_dist` | Age/sex recipe weights for one municipality |
| `list_runs` | List körningar (requires API URL) |
| `get_run` | Fetch one körning (requires API URL) |

## In-app help chat

The admin UI includes a floating help chatbot on **every page** (same WebSocket streaming as persona chat). It uses OKF manuals plus **read-only** live data (library counts, open entity, injected current view). **SCB PxWebApi 2** is available only when the operator explicitly enables **Include SCB statistics** in the help panel (off by default). It never writes to the database.

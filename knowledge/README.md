# Knowledge bundles (OKF)

End-user knowledge for Socialism, stored as [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf) (OKF) bundles.

| Path | Audience | Purpose |
| ---- | -------- | ------- |
| [`manual/`](manual/) | Operators using the Swedish UI | How-to guides (körningar, personas, …) |
| [`docs/`](../docs/) | Developers | Setup, architecture, engineering notes |

Do not mix these: OKF manuals describe **what the user can do**; `docs/` explains **how the system works**.

## Validate

From the repo root:

```bash
make knowledge-validate
# or:
npx -y @mfdaves/okf-mcp@0.3.3 --project ./okf.project.yaml validate
```

Project config: [`okf.project.yaml`](../okf.project.yaml).

## MCP (later)

The same project file can back an OKF MCP server:

```bash
npx -y @mfdaves/okf-mcp@0.3.3 --project ./okf.project.yaml mcp
```

## Writing guides

See conventions in [`manual/`](manual/) and root [`AGENTS.md`](../AGENTS.md). Prefer Swedish, reuse existing tags, and keep guides free of implementation detail.

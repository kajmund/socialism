.PHONY: help backend frontend start install knowledge-validate

# Pinned OKF CLI (validate + future MCP). Not a runtime app dependency.
OKF_MCP_PKG := @mfdaves/okf-mcp@0.3.3

help:
	@echo "Targets:"
	@echo "  make start               Start backend + frontend together"
	@echo "  make backend             Start FastAPI (uvicorn --reload) on :8000"
	@echo "  make frontend            Start Vite dev server on :5173"
	@echo "  make install             Install backend + frontend deps"
	@echo "  make knowledge-validate  Validate OKF manual bundle"
	@echo "  make knowledge-mcp       Run OKF MCP server (stdio)"

backend:
	cd backend && uv run uvicorn app.main:app --reload

frontend:
	cd frontend && pnpm dev

start:
	@trap 'kill 0' EXIT; \
	(cd backend && uv run uvicorn app.main:app --reload) & \
	(cd frontend && pnpm dev) & \
	wait

install:
	cd backend && uv sync
	cd frontend && pnpm install

knowledge-validate:
	npx -y $(OKF_MCP_PKG) --project ./okf.project.yaml validate

knowledge-mcp:
	cd integrations/mcp && uv run python server.py

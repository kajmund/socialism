.PHONY: help backend frontend word-addin start install test test-backend test-frontend test-word-addin knowledge-validate

# Pinned OKF CLI (validate + future MCP). Not a runtime app dependency.
OKF_MCP_PKG := @mfdaves/okf-mcp@0.3.3

help:
	@echo "Targets:"
	@echo "  make start               Start backend + frontend together"
	@echo "  make backend             Start FastAPI (uvicorn --reload) on :8000"
	@echo "  make frontend            Start Vite dev server on :5173"
	@echo "  make word-addin          Start Word add-in Vite server on :3000"
	@echo "  make install             Install backend + frontend + word-addin deps"
	@echo "  make test                Backend pytest + frontend and word-addin lint/vitest"
	@echo "  make test-backend        Backend pytest (excludes smoke)"
	@echo "  make test-frontend       Frontend oxlint + vitest"
	@echo "  make test-word-addin     Word add-in oxlint + vitest"
	@echo "  make knowledge-validate  Validate OKF manual bundle"
	@echo "  make knowledge-mcp       Run OKF MCP server (stdio)"

# uv run without --extra oasis uninstalls camel-oasis. Keep it when .env asks for OASIS.
BACKEND_UV_EXTRA := $(shell grep -E '^SIMULATION_ENGINE=oasis$$' backend/.env 2>/dev/null >/dev/null && echo --extra oasis)

backend:
	cd backend && uv run $(BACKEND_UV_EXTRA) uvicorn app.main:app --reload

frontend:
	cd frontend && pnpm dev

word-addin:
	cd word-addin && pnpm dev

start:
	@bash -eu -c '\
	  cleanup() { \
	    trap - EXIT INT TERM HUP; \
	    for pid in $$(jobs -p); do \
	      kill -TERM -$$pid 2>/dev/null || kill -TERM $$pid 2>/dev/null || true; \
	    done; \
	    wait 2>/dev/null || true; \
	    for port in 8000 5173; do \
	      pids=$$(lsof -nP -t -iTCP:$$port -sTCP:LISTEN 2>/dev/null || true); \
	      if [ -n "$$pids" ]; then kill -TERM $$pids 2>/dev/null || true; fi; \
	    done; \
	    sleep 0.2; \
	    for port in 8000 5173; do \
	      pids=$$(lsof -nP -t -iTCP:$$port -sTCP:LISTEN 2>/dev/null || true); \
	      if [ -n "$$pids" ]; then kill -KILL $$pids 2>/dev/null || true; fi; \
	    done; \
	  }; \
	  trap cleanup EXIT INT TERM HUP; \
	  (cd backend && uv run $(BACKEND_UV_EXTRA) uvicorn app.main:app --reload) & \
	  (cd frontend && pnpm dev) & \
	  wait \
	'

install:
	cd backend && uv sync $(BACKEND_UV_EXTRA)
	cd frontend && pnpm install
	cd word-addin && pnpm install

test: test-backend test-frontend test-word-addin

test-backend:
	cd backend && uv run $(BACKEND_UV_EXTRA) pytest

test-frontend:
	cd frontend && pnpm lint
	cd frontend && pnpm test

test-word-addin:
	cd word-addin && pnpm lint
	cd word-addin && pnpm test

knowledge-validate:
	npx -y $(OKF_MCP_PKG) --project ./okf.project.yaml validate

knowledge-mcp:
	cd integrations/mcp && uv run python server.py

.PHONY: help backend frontend word-addin elk-proxy kibana-proxy start install test test-backend test-frontend test-word-addin knowledge-validate

# Pinned OKF CLI (validate + future MCP). Not a runtime app dependency.
OKF_MCP_PKG := @mfdaves/okf-mcp@0.3.3

FLYCTL ?= flyctl
ELASTICSEARCH_FLY_APP ?= socialism-elasticsearch
ELASTICSEARCH_PROXY_PORT ?= 19200
ELASTICSEARCH_REMOTE_PORT ?= 9200
KIBANA_FLY_APP ?= socialism-kibana
KIBANA_PROXY_PORT ?= 5601
KIBANA_REMOTE_PORT ?= 5601

# uvicorn --reload is on by default. Pass RELOAD=0 to keep a single backend process.
RELOAD ?= 1
BACKEND_UVICORN_FLAGS := $(if $(filter 0,$(RELOAD)),,--reload)

help:
	@echo "Targets:"
	@echo "  make start               Start ELK proxies + backend + frontend together"
	@echo "  make start RELOAD=0      Same, backend without uvicorn --reload"
	@echo "  make backend             Start FastAPI (uvicorn --reload) on :8000"
	@echo "  make backend RELOAD=0    Start FastAPI without --reload"
	@echo "  make frontend            Start Vite dev server on :5173"
	@echo "  make word-addin          Start Word add-in Vite server on :3000"
	@echo "  make elk-proxy           Proxy local :$(ELASTICSEARCH_PROXY_PORT) to Elasticsearch on Fly"
	@echo "  make kibana-proxy        Proxy local :$(KIBANA_PROXY_PORT) to Kibana on Fly"
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
	cd backend && uv run $(BACKEND_UV_EXTRA) uvicorn app.main:app $(BACKEND_UVICORN_FLAGS)

frontend:
	cd frontend && pnpm dev

word-addin:
	cd word-addin && pnpm dev

elk-proxy:
	@FLYCTL="$(FLYCTL)" \
	  FLY_APP="$(ELASTICSEARCH_FLY_APP)" \
	  LOCAL_PORT="$(ELASTICSEARCH_PROXY_PORT)" \
	  REMOTE_PORT="$(ELASTICSEARCH_REMOTE_PORT)" \
	  PROXY_LABEL="Elasticsearch proxy" \
	  ./scripts/elk-proxy.sh

kibana-proxy:
	@FLYCTL="$(FLYCTL)" \
	  FLY_APP="$(KIBANA_FLY_APP)" \
	  LOCAL_PORT="$(KIBANA_PROXY_PORT)" \
	  REMOTE_PORT="$(KIBANA_REMOTE_PORT)" \
	  PROXY_LABEL="Kibana proxy" \
	  ./scripts/elk-proxy.sh

start:
	@bash -eu -c '\
	  es_proxy_pid=""; \
	  kibana_proxy_pid=""; \
	  backend_pid=""; \
	  frontend_pid=""; \
	  cleanup() { \
	    trap - EXIT INT TERM HUP; \
	    for pid in $$(jobs -p); do \
	      kill -TERM -$$pid 2>/dev/null || kill -TERM $$pid 2>/dev/null || true; \
	    done; \
	    wait 2>/dev/null || true; \
	    for port in 8000 5173 $(ELASTICSEARCH_PROXY_PORT) $(KIBANA_PROXY_PORT); do \
	      pids=$$(lsof -nP -t -iTCP:$$port -sTCP:LISTEN 2>/dev/null || true); \
	      if [ -n "$$pids" ]; then kill -TERM $$pids 2>/dev/null || true; fi; \
	    done; \
	    sleep 0.2; \
	    for port in 8000 5173 $(ELASTICSEARCH_PROXY_PORT) $(KIBANA_PROXY_PORT); do \
	      pids=$$(lsof -nP -t -iTCP:$$port -sTCP:LISTEN 2>/dev/null || true); \
	      if [ -n "$$pids" ]; then kill -KILL $$pids 2>/dev/null || true; fi; \
	    done; \
	  }; \
	  wait_http() { \
	    name=$$1; \
	    url=$$2; \
	    pid=$$3; \
	    attempts=$$4; \
	    i=0; \
	    while [ $$i -lt $$attempts ]; do \
	      if curl --fail --silent --max-time 8 -o /dev/null "$$url"; then \
	        return 0; \
	      fi; \
	      if ! kill -0 $$pid 2>/dev/null; then \
	        wait $$pid || true; \
	        echo "make start: $$name stopped before it became ready." >&2; \
	        exit 1; \
	      fi; \
	      i=$$((i + 1)); \
	      sleep 0.5; \
	    done; \
	    echo "make start: $$name did not become ready at $$url." >&2; \
	    exit 1; \
	  }; \
	  trap cleanup EXIT INT TERM HUP; \
	  command -v curl >/dev/null 2>&1 || { echo "make start: curl is required for the Elasticsearch and Kibana health checks." >&2; exit 1; }; \
	  FLYCTL="$(FLYCTL)" \
	    FLY_APP="$(ELASTICSEARCH_FLY_APP)" \
	    LOCAL_PORT="$(ELASTICSEARCH_PROXY_PORT)" \
	    REMOTE_PORT="$(ELASTICSEARCH_REMOTE_PORT)" \
	    PROXY_LABEL="Elasticsearch proxy" \
	    ./scripts/elk-proxy.sh & \
	  es_proxy_pid=$$!; \
	  FLYCTL="$(FLYCTL)" \
	    FLY_APP="$(KIBANA_FLY_APP)" \
	    LOCAL_PORT="$(KIBANA_PROXY_PORT)" \
	    REMOTE_PORT="$(KIBANA_REMOTE_PORT)" \
	    PROXY_LABEL="Kibana proxy" \
	    ./scripts/elk-proxy.sh & \
	  kibana_proxy_pid=$$!; \
	  wait_http "Elasticsearch proxy" "http://127.0.0.1:$(ELASTICSEARCH_PROXY_PORT)/_cluster/health" $$es_proxy_pid 60; \
	  echo "make start: Elasticsearch is ready on http://127.0.0.1:$(ELASTICSEARCH_PROXY_PORT)"; \
	  wait_http "Kibana proxy" "http://127.0.0.1:$(KIBANA_PROXY_PORT)/api/status" $$kibana_proxy_pid 120; \
	  echo "make start: Kibana is ready on http://127.0.0.1:$(KIBANA_PROXY_PORT)"; \
	  (cd backend && uv run $(BACKEND_UV_EXTRA) uvicorn app.main:app $(BACKEND_UVICORN_FLAGS)) & \
	  backend_pid=$$!; \
	  (cd frontend && pnpm dev) & \
	  frontend_pid=$$!; \
	  while :; do \
	    for process in "Elasticsearch proxy:$$es_proxy_pid" "Kibana proxy:$$kibana_proxy_pid" "backend:$$backend_pid" "frontend:$$frontend_pid"; do \
	      name=$${process%%:*}; \
	      pid=$${process#*:}; \
	      if ! kill -0 $$pid 2>/dev/null; then \
	        status=0; \
	        wait $$pid || status=$$?; \
	        if [ $$status -eq 0 ]; then status=1; fi; \
	        echo "make start: $$name stopped; shutting down the local stack." >&2; \
	        exit $$status; \
	      fi; \
	    done; \
	    sleep 1; \
	  done \
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

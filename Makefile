.PHONY: help backend frontend start install

help:
	@echo "Targets:"
	@echo "  make start     Start backend + frontend together"
	@echo "  make backend   Start FastAPI (uvicorn --reload) on :8000"
	@echo "  make frontend  Start Vite dev server on :5173"
	@echo "  make install   Install backend + frontend deps"

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

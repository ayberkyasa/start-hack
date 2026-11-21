.PHONY: setup backend frontend check build

setup:
	cd backend && uv sync --locked
	npm --prefix frontend ci

backend:
	cd backend && uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

frontend:
	npm --prefix frontend run dev

check:
	cd backend && uv run --locked python -m compileall -q app
	npm --prefix frontend run typecheck

build:
	npm --prefix frontend run build

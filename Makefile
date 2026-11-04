.PHONY: setup test lint fmt ci tools serve

setup:                     ## install the package and dev dependencies into .venv
	uv sync --locked --extra dev --group build --no-install-project
	uv sync --locked --extra dev --group build --no-build-isolation

test:
	uv run --locked --no-sync pytest -q

lint:
	uv run --locked --no-sync ruff check .
	uv run --locked --no-sync ruff format --check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

ci: lint test             ## what CI runs; run this before opening a PR

tools:                     ## list the tools the current configuration exposes
	uv run pretix-agent-mcp tools

serve:
	uv run pretix-agent-mcp serve

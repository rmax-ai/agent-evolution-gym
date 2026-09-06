.PHONY: lint format typecheck test verify sync

sync:
	uv sync

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run ty check src

test:
	uv run pytest -q

# Full verification gate (run in order, stop on first failure)
verify:
	uv run ruff check .
	uv run ty check src
	uv run pytest -q

.PHONY: test

test:
	uv run ruff format --check .
	uv run ruff check .
	uv run pytest
	uv run mypy .

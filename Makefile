.PHONY: test full-test

test:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy .
	uv run pytest

full-test: test
	uv run pytest -m slow

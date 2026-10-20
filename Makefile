.PHONY: install fmt lint typecheck test security check

install:
	uv sync

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run mypy

test:
	uv run pytest --cov --cov-report=term-missing

security:
	uv run bandit -q -c pyproject.toml -r app tools_mcp evals
	uv run detect-secrets-hook --baseline .secrets.baseline $$(git ls-files)
	uv export --format requirements-txt --no-hashes --no-emit-project -q > .audit-reqs.txt && uv run pip-audit -r .audit-reqs.txt --progress-spinner off

check: lint typecheck test security

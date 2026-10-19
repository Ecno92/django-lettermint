.PHONY: check build

check:  ## Lint, format check and tests with the 100% coverage gate
	uv run ruff check .
	uv run ruff format . --check
	uv run pytest --cov --cov-report=term-missing --cov-fail-under=100

build:  ## Build the sdist and wheel into dist/ and check their metadata
	rm -rf dist
	uv build
	uv tool run twine check dist/*

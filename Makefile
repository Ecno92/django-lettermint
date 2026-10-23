.PHONY: check check-all build publish publish-test

PYTHONS ?= 3.12 3.13 3.14

check:  ## Lint, format check and tests with the 100% coverage gate
	uv run ruff check .
	uv run ruff format . --check
	uv run pytest --cov --cov-report=term-missing --cov-fail-under=100

check-all:  ## Run check on every supported Python version
	@for v in $(PYTHONS); do \
		echo "== Python $$v"; \
		UV_PROJECT_ENVIRONMENT=.venv-$$v UV_PYTHON=$$v $(MAKE) check || exit 1; \
	done

build:  ## Build the sdist and wheel into dist/ and check their metadata
	rm -rf dist
	uv build
	uv tool run twine check dist/*

publish-test:
	uvx twine upload --repository testpypi dist/*

publish:
	uvx twine upload --repository pypi dist/*

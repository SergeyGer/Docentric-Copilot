.DEFAULT_GOAL := help
PYTHON ?= python3.12
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help install install-dev install-web test test-cov lint typecheck format bench eval openapi dev-api dev-web docker-up docker-down clean ci

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Create the virtualenv and install the package
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e .

install-dev: install ## Install development dependencies
	$(BIN)/pip install -e ".[dev]"

install-web: ## Install frontend dependencies
	cd apps/web && npm ci

test: ## Run the test suite
	$(BIN)/pytest

test-cov: ## Run tests with the coverage gate for the deterministic core
	$(BIN)/pytest --cov=docentric_copilot --cov-report=term-missing --cov-report=xml --cov-fail-under=85

lint: ## Lint Python sources
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

typecheck: ## Type check Python sources
	$(BIN)/mypy packages services

format: ## Auto-format Python sources
	$(BIN)/ruff check --fix .
	$(BIN)/ruff format .

bench: ## Run latency benchmarks (100 runs per fixture)
	$(BIN)/python benchmarks/run_benchmarks.py --runs 100

eval: ## Run the AI evaluation harness with the deterministic baseline
	$(BIN)/python benchmarks/run_evaluation.py

openapi: ## Export the OpenAPI document to docs/openapi.json
	$(BIN)/python scripts/export_openapi.py

dev-api: ## Run the API with autoreload
	$(BIN)/uvicorn docentric_copilot.api.main:app --reload --port 8000

dev-web: ## Run the web app in development mode
	cd apps/web && npm run dev

docker-up: ## Build and start the full stack
	docker compose up --build -d

docker-down: ## Stop the stack
	docker compose down

ci: lint typecheck test-cov ## Everything CI runs for Python

clean: ## Remove local caches and build output
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov coverage.xml dist build .data
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +

docs-check:
	python scripts/check_docs_links.py

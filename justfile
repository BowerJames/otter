# Otter — common dev tasks

# List available recipes (default)
default:
    @just --list

# Install dependencies into .venv
sync:
    uv sync

# Run the unit tests
test:
    uv run pytest

# Run the integration tests, which reach real resources such as the file system
test-integration:
    uv run pytest -m integration

# Run the end-to-end tests, which run the startup code with the production factories
test-e2e:
    uv run pytest -m e2e

# Type check
typecheck:
    uv run mypy src tests

# Lint
lint:
    uv run ruff check .

# Check the import rules of the project structure
lint-imports:
    uv run lint-imports

# Check formatting without changing files
format-check:
    uv run ruff format --check .

# Fix lint issues and reformat
fix:
    uv run ruff check --fix .
    uv run ruff format .

# Run all checks (lint, imports, format, types, and every kind of test)
check: lint lint-imports format-check typecheck test test-integration test-e2e

# Chat with an agent session, e.g. just tui --model-name glm-5.3 --model-type chat-completions --provider zai [--session-file session.jsonl]
tui *args:
    uv run python -m otter.infrastructure.entrypoints.tui {{args}}

# Remove tool caches and build artifacts
clean:
    rm -rf .mypy_cache .pytest_cache .ruff_cache .coverage coverage.xml htmlcov dist build

# Reinstall from scratch
nuke: clean
    rm -rf .venv
    just sync

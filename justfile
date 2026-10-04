# Otter — common dev tasks

# List available recipes (default)
default:
    @just --list

# Install dependencies into .venv
sync:
    uv sync

# Run tests
test:
    uv run pytest

# Type check
typecheck:
    uv run mypy src tests

# Lint
lint:
    uv run ruff check .

# Check formatting without changing files
format-check:
    uv run ruff format --check .

# Fix lint issues and reformat
fix:
    uv run ruff check --fix .
    uv run ruff format .

# Run all checks (lint, format, types, tests)
check: lint format-check typecheck test

# Remove tool caches and build artifacts
clean:
    rm -rf .mypy_cache .pytest_cache .ruff_cache .coverage coverage.xml htmlcov dist build

# Reinstall from scratch
nuke: clean
    rm -rf .venv
    just sync

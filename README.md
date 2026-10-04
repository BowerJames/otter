# otter

A lightweight framework for building AI agents.

## Development

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```sh
uv sync          # create venv and install dev dependencies
```

### Common tasks

If you have [just](https://github.com/casey/just) installed:

```sh
just sync    # create venv and install dev dependencies
just check   # lint + format check + typecheck + test
just fix     # auto-fix lint issues and reformat
```

Or run the tools directly:

```sh
uv run pytest            # run tests
uv run mypy src tests    # type check
uv run ruff check .      # lint
uv run ruff format .     # format
```

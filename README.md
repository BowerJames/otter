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

### Trying a session out

`scripts/tui.py` opens a terminal chat with an agent session:

```sh
just tui --model-name glm-5.3 --model-type chat-completions --provider zai
```

`--model-type` is `chat-completions` or `responses`; the providers `openai` and `zai` serve both.

Add `--session-file session.jsonl` to keep the session in a file: running again with the same
file picks the session up where it left off.

The provider's API key is read from `<PROVIDER>_API_KEY`, which can be set in a `.env` file
at the root of the repository.

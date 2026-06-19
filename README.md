# otter

Otter AI — Python monorepo.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (package manager)
- Python 3.12+ (managed by uv via `.python-version`)

## Setup

Install dependencies and create the virtual environment:

```bash
uv sync
```

Enable the local pre-commit hook (run once per clone):

```bash
git config core.hooksPath .githooks
```

## Monorepo layout

Packages live under [`packages/`](./packages):

```
packages/
└── otter_ai/        # the otter-ai package (import as `otter_ai`)
    ├── src/otter_ai/
    └── tests/
```

The repository root is a [virtual uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/).
All packages and dev dependencies share a single `.venv` at the root.

## `otter-ai` context model

The `otter-ai` package is a **data-only** model for representing LLM conversation
context. It contains no LLMs, providers, APIs, or streaming — only the
Pydantic v2 data structures a conversation is built from:

- [`Context`](./packages/otter_ai/src/otter_ai/context.py) — the top-level
  conversation (`system_prompt`, `messages`, `tools`), JSON-serializable so a
  context can be persisted and replayed elsewhere.
- [`Message`](./packages/otter_ai/src/otter_ai/messages.py) — a discriminated
  union of `UserMessage`, `AssistantMessage`, and `ToolResultMessage`.
- Content blocks in `content.py`: `TextContent`, `ImageContent`,
  `ThinkingContent`, `ToolCall`.
- [`Tool`](./packages/otter_ai/src/otter_ai/tools.py) — tool definitions whose
  `parameters` accept a JSON-Schema `dict` or a Pydantic `BaseModel` subclass.
- [`Usage`](./packages/otter_ai/src/otter_ai/usage.py) and diagnostics for
  per-turn accounting.

`AssistantMessage` also carries inert provenance (`api`, `provider`, `model`,
`response_model`, `response_id`) and accounting (`usage`, `stop_reason`,
`error_message`) fields. Otter never interprets these — they are preserved so a
context can be replayed by a provider package built on top.

### Opt-in replay normalization

[`normalize.py`](./packages/otter_ai/src/otter_ai/normalize.py) exposes
**opt-in** utilities that prepare a message list for replay to a model:

- `drop_unreplayable_assistant_turns` — removes assistant turns whose
  `stop_reason` is `"error"` or `"aborted"`.
- `fill_missing_tool_results` — inserts synthetic `is_error=True` tool results
  for any `tool_call` not followed by its result.
- `normalize_messages` — applies both.

These are **never applied automatically** (they would corrupt a normal
tool-execution loop); call them explicitly only when preparing to replay.

### Quick example

```python
from otter_ai import Context, UserMessage, normalize_messages

context = Context(
    system_prompt="You are helpful.",
    messages=[UserMessage(role="user", content="Hi!", timestamp=0)],
)

# A Context round-trips through plain JSON.
restored = Context.model_validate_json(context.model_dump_json())
assert restored == context

# Opt-in replay prep (only when you intend to send to a model elsewhere):
replay_ready = normalize_messages(context.messages)
```

## Tooling

| Tool        | Purpose                 | Config                         |
| ----------- | ----------------------- | ------------------------------ |
| [ruff]      | Linting + formatting    | `[tool.ruff]` in `pyproject.toml` |
| [mypy]      | Static type checking    | `[tool.mypy]` in `pyproject.toml` |
| [pytest]    | Testing (incl. `async`) | `[tool.pytest.ini_options]`    |

[ruff]: https://docs.astral.sh/ruff/
[mypy]: https://mypy-lang.org/
[pytest]: https://docs.pytest.org/

### Run checks

```bash
uv run pytest                         # run tests (async tests run automatically)
uv run ruff check .                   # lint
uv run ruff format --check .          # format check (use without --check to apply)
uv run mypy                           # type check
```

### Pre-commit hook

Once enabled, every `git commit` runs:

1. `ruff check --fix` and `ruff format` on staged Python files, **auto-staging** the fixes, then
2. `mypy` on the whole workspace.

The commit is rejected if any check fails. Tool versions are pinned via `uv run` (see `uv.lock`).

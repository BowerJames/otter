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
└── otter_ai_core/        # the otter-ai-core package (import as `otter_ai_core`)
    ├── src/otter_ai_core/
    └── tests/
```

The repository root is a [virtual uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/).
All packages and dev dependencies share a single `.venv` at the root.

## `otter-ai-core` context model

`otter-ai-core` is the **driving package** of the monorepo: it owns the core
types and data models that the other packages (`otter-ai-chat-completions`,
`otter-ai-assistant-provider-stream`) build on — for example, its
`AssistantMessageStreamFn` defines the core type that the Chat Completions seam
implements.

The `otter-ai-core` package models LLM conversation context and the streaming
runtime used to build it. It defines **no LLMs, providers, APIs, transports,
API registry, or `stream()` dispatch** — only the Pydantic v2 data structures a
conversation is built from, the streaming-event protocol, and a
generic async stream runtime:

- [`Context`](./packages/otter_ai_core/src/otter_ai_core/context.py) — the top-level
  conversation (`system_prompt`, `messages`, `tools`), JSON-serializable so a
  context can be persisted and replayed elsewhere.
- [`Message`](./packages/otter_ai_core/src/otter_ai_core/messages.py) — a discriminated
  union of `UserMessage`, `AssistantMessage`, and `ToolResultMessage`.
- Content blocks in `content.py`: `TextContent`, `ImageContent`,
  `ThinkingContent`, `ToolCall`.
- [`Tool`](./packages/otter_ai_core/src/otter_ai_core/tools.py) — tool definitions whose
  `parameters` accept a JSON-Schema `dict` or a Pydantic `BaseModel` subclass.
- [`Usage`](./packages/otter_ai_core/src/otter_ai_core/usage.py) and diagnostics for
  per-turn accounting.
- [`model_events.py`](./packages/otter_ai_core/src/otter_ai_core/model_events.py) — the streaming-event
  protocol: `AssistantMessageEvent`, `UserMessageEvent`, and
  `ToolResultMessageEvent` families (each a discriminated union on `type`),
  the plain unions `MessageEvent` (assistant + user) and `ContextItemEvent`
  (all three).
- [`stream.py`](./packages/otter_ai_core/src/otter_ai_core/stream.py) — a generic async
  stream runtime (`Stream` / `StreamWriter` / `create_stream`) plus the typed
  message-stream aliases. See [Generic stream runtime](#generic-stream-runtime).

`AssistantMessage` also carries inert provenance (`api`, `provider`, `model`,
`response_model`, `response_id`) and accounting (`usage`, `stop_reason`,
`error_message`) fields. Otter never interprets these — they are preserved so a
context can be replayed by a provider package built on top.

### Opt-in replay normalization

[`normalize.py`](./packages/otter_ai_core/src/otter_ai_core/normalize.py) exposes
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
from otter_ai_core import Context, UserMessage, normalize_messages

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

### Generic stream runtime

[`stream.py`](./packages/otter_ai_core/src/otter_ai_core/stream.py) is a faithful
Python/`asyncio` port of pi-ai's `EventStream` push-queue. The runtime is split
into a consumer and a producer sharing one queue:

- `Stream[TEvent]` — the consumer; iterate with `async for`.
- `StreamWriter[TEvent]` — the producer; call `push(event)` for every event
  (including the terminal `done`/`error`), then `end()`.
- `create_stream()` — returns a linked `(Stream, StreamWriter)` pair.

Typed aliases specialize it: `AssistantMessageStream`, `UserMessageStream`,
`MessageEventStream` (assistant + user), `ContextItemStream` (all three), each
with a matching `*Writer` alias.

There is **no `result()`** — pi-ai's `result()` is single-item-only sugar that
doesn't generalize to multi-item streams (`MessageEventStream`/
`ContextItemStream`); consumers read the terminal `done`/`error` event directly.

`Stream` and `StreamWriter` are runtime objects and are **not** JSON-serializable
(unlike `Context`); the serializable data model is unchanged.

```python
import asyncio

from otter_ai_core import AssistantDoneEvent, AssistantMessage, create_stream


async def main() -> None:
    stream, writer = create_stream()

    async def produce() -> None:
        msg = AssistantMessage(
            role="assistant",
            content=[],
            api="anthropic-messages",
            provider="anthropic",
            model="claude-3",
            usage=...,  # a Usage instance
            stop_reason="stop",
            timestamp=0,
        )
        # Push every event, including the terminal ``done``, then end:
        writer.push(
            AssistantDoneEvent(role="assistant", type="done", reason="stop", message=msg)
        )
        writer.end()

    task = asyncio.create_task(produce())
    async for event in stream:  # the terminal "done" event is the last one yielded
        ...
    await task
```

Otter defines the runtime and types only — **no providers, no registry, no
`stream()` dispatch**.

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

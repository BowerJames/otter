# otter

Otter AI — Python monorepo (a [uv](https://docs.astral.sh/uv/) workspace).

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
├── otter_ai_core/     # the otter-ai-core package (import as `otter_ai_core`)
└── otter_ai_logging/  # the otter-ai-logging package (import as `otter_ai_logging`)
```

The repository root is a [virtual uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/)
(`members = ["packages/*"]`), so additional packages can be dropped under
`packages/` without further configuration.

## `otter-ai-core`

`otter-ai-core` is the **driving package** of the monorepo: it owns the core
types and data models a conversation is built from, plus the generic async
streaming runtimes built on top of them. It defines **no LLMs, providers,
APIs, transports, API registry, or `stream()` dispatch** — only the Pydantic v2
data structures, a generic async channel runtime, an abortable stream facade
layered over it, and the seam types a provider/transport package will implement.

### Context model

- [`Context`](./packages/otter_ai_core/src/otter_ai_core/context/context.py) — the top-level
  conversation (`system_prompt`, `items`, `tools`), JSON-serializable so a
  context can be persisted and replayed elsewhere.
- [`ContextItem`](./packages/otter_ai_core/src/otter_ai_core/context/context_item.py) — the
  `{id, message}` wrapper layer between `Context` and `Message`. The `id` is
  caller/provider-supplied; it is **not** generated inside assistant message
  streams.
- [`Message`](./packages/otter_ai_core/src/otter_ai_core/context/messages.py) — a discriminated
  union of `UserMessage`, `AssistantMessage`, and `ToolResultMessage`.
- Content blocks in [`content.py`](./packages/otter_ai_core/src/otter_ai_core/context/content.py):
  `TextContent`, `ImageContent`, `ThinkingContent`, `ToolCall`.
- [`Tool`](./packages/otter_ai_core/src/otter_ai_core/context/tool.py) — tool definitions whose
  `parameters` accept a JSON-Schema `dict` or a Pydantic `BaseModel` subclass.
- [`Usage`](./packages/otter_ai_core/src/otter_ai_core/context/usage.py) and diagnostics for
  per-turn accounting.

`AssistantMessage` also carries inert provenance (`api`, `provider`, `model`,
`response_model`, `response_id`) and accounting (`usage`, `stop_reason`,
`error_message`) fields. Otter never interprets these — they are preserved so a
context can be replayed by a provider package built on top.

### Quick example

```python
from otter_ai_core import Context, UserMessage, context_item

context = Context(
    system_prompt="You are helpful.",
    items=[
        context_item(
            message=UserMessage(role="user", content="Hi!", timestamp=0),
            id="u1",
        )
    ],
)

# A Context round-trips through plain JSON.
restored = Context.model_validate_json(context.model_dump_json())
assert restored == context
```

### Assistant message stream

The [`assistant_message_stream/`](./packages/otter_ai_core/src/otter_ai_core/assistant_message_stream/)
subpackage defines the streaming-event **protocol** (`AssistantMessageEvent`
family) and the **typed stream aliases** (`AssistantMessageStreamClient` /
`AssistantMessageStreamBackend` / the `AssistantMessageStreamFnBuilder` seam).
Import from `otter_ai_core.assistant_message_stream`.

### Generic channel runtime

[`channel.py`](./packages/otter_ai_core/src/otter_ai_core/channel.py) is a faithful
Python/`asyncio` port of pi-ai's `EventStream` push-queue. The runtime is a
single-consumer queue split into a read end and a write end sharing one queue:

- `ChannelReader[TEvent]` — the read end; iterate with `async for`.
- `ChannelWriter[TEvent]` — the write end; call `push(event)` for every event
  (including the terminal `done`/`error`), then `end()`.
- `create_channel()` — returns a `ChannelPair[TEvent]` whose `.writer` is
  the `ChannelWriter` and `.reader` is the `ChannelReader`.

Layered over the channel is an **abortable stream facade**
([`stream.py`](./packages/otter_ai_core/src/otter_ai_core/stream.py)):
`StreamClient[TEvent]` (iterate with `async for` / `await anext()`, and call
`abort()` to signal the producer) paired with `StreamBackend[TEvent]` (push /
end, and observe `abort_signal`), sharing one queue and one `asyncio.Event`;
`create_stream()` returns a `StreamPair`. The abort signal is **intrinsic to
the stream** (not a function argument): the producer creates it with
`create_stream()`, the consumer drives it with `abort()`. There
is **no `result()`** — consumers read the terminal `done`/`error` event
directly.

`ChannelReader`, `ChannelWriter`, `StreamClient`, and `StreamBackend` are
runtime objects and are **not** JSON-serializable (unlike `Context`); the
serializable data model is unchanged.

### Other core subpackages

- [`bidirectional_channel.py`](./packages/otter_ai_core/src/otter_ai_core/bidirectional_channel.py)
  / [`builder.py`](./packages/otter_ai_core/src/otter_ai_core/builder.py) — the bidirectional
  channel pair and the generic `BuilderFn[TOptions, TResult]` alias both
  producer seams fold onto.
- [`hook.py`](./packages/otter_ai_core/src/otter_ai_core/hook.py) — the generic async
  `Hook[TEvent, TResponse]` alias.
- [`provider_api_model_options/`](./packages/otter_ai_core/src/otter_ai_core/provider_api_model_options/) —
  pure-data enumerations/types (`KnownApis`, `KnownProviders`, `ThinkingLevel`)
  a dispatch layer keys on.

```python
import asyncio

from otter_ai_core import AssistantMessage, create_channel
from otter_ai_core.assistant_message_stream import AssistantDoneEvent


async def main() -> None:
    wiring = create_channel()
    reader = wiring.reader
    writer = wiring.writer

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
    async for event in reader:  # the terminal "done" event is the last one yielded
        ...
    await task
```

Otter defines the runtime and types only — **no providers, no registry, no
`stream()` dispatch**.

## `otter-ai-logging`

`otter-ai-logging` configures the stdlib [`logging`](https://docs.python.org/3/library/logging.html)
module for the monorepo's logging conventions. It depends on nothing but the
standard library.

- **Line format** — `<timestamp_utc> <level> <message>` (ISO-8601 UTC), e.g.
  `2026-07-09T10:56:29Z INFO user 42 authenticated`.
- **Stream routing** — `DEBUG`/`INFO`/`WARNING` → stdout, `ERROR` → stderr
  (stderr only; never mirrored). `ERROR` is the alertable channel.
- **Level** — driven by the `LOG_LEVEL` environment variable (one of
  `DEBUG`/`INFO`/`WARNING`/`ERROR`), defaulting to `INFO`. The canonical level
  set is four levels; `CRITICAL`/unknown values raise `ValueError`.

Application code configures logging once at startup; libraries and modules
obtain a logger with the stdlib idiom `logging.getLogger(__name__)`.

```python
from otter_ai_logging import configure_logging

configure_logging()  # reads LOG_LEVEL (default INFO); idempotent

import logging

log = logging.getLogger(__name__)
log.info("user %s authenticated", 42)        # -> stdout
log.error("database connection refused")     # -> stderr (alertable)
```

## Tooling

| Tool        | Purpose                 | Config                         |
| ----------- | ----------------------- | ------------------------------ |
| [ruff]      | Linting + formatting    | `[tool.ruff]` in `pyproject.toml`  |
| [mypy]      | Static type checking    | `[tool.mypy]` in `pyproject.toml`  |
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

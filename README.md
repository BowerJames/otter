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
├── otter_ai_agent/      # the otter-ai-agent package (agent loop over a ModelSession)
├── otter_ai_core/       # the otter-ai-core package (import as `otter_ai_core`)
└── …                    # provider/transport packages (chat-completions, realtime, …)
```

The repository root is a [virtual uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/).

## `otter-ai-agent`

`otter-ai-agent` is the **turn / tool-execution layer** that sits above
`otter-ai-core`'s reactive [`ModelSession`](./packages/otter_ai_core/src/otter_ai_core/model_session/model_session.py).
It ports the agent-loop semantics of pi's `@earendil-works/pi-agent-core` (turn
loop, sequential/parallel tool execution, steering/follow-up queues,
`before_tool_call` / `after_tool_call` hooks) onto otter's **reactive** session
model — and runs unchanged over a Realtime WebSocket *or* a wrapped
chat-completions stream, because it depends only on the session abstraction.

- [`Agent`](./packages/otter_ai_agent/src/otter_ai_agent/agent.py) — the agent:
a per-run coroutine driver implements the turn FSM (request → await terminal →
execute tools → loop), subscribing to the session bus internally. The
per-turn "await one response" coupling is a private driver detail; the session
stays fully reactive.
- [`AgentTool`](./packages/otter_ai_agent/src/otter_ai_agent/types.py) — pairs a
declarative [`Tool`](./packages/otter_ai_core/src/otter_ai_core/tools.py) (the
schema sent to the model) with an async `execute`; `before_tool_call` /
`after_tool_call` / `should_stop_after_turn` / `prepare_next_turn` hooks are
supported (`prepare_next_turn` is context-view-only — a session is bound to one
model at connect).
- [`AgentEvent`](./packages/otter_ai_agent/src/otter_ai_agent/events.py) — a
separate event family + `AgentBus` (the agent's own vocabulary, distinct from
the session's reduced `SessionEvent`s). Consume via `agent.on(...)` (persistent
subscriber), `agent.stream(...)` (`async for`), or `await agent.run(...)`.
All packages and dev dependencies share a single `.venv` at the root.

## `otter-ai-core` context model

`otter-ai-core` is the **driving package** of the monorepo: it owns the core
types and data models that the other packages (`otter-ai-chat-completions`,
`otter-ai-assistant-provider-stream`) build on — for example, its
`AssistantMessageStreamFnBuilder` (under the `assistant_message_stream`
subpackage) defines the core producer-seam type that the Chat Completions
seam implements, and its `ModelConnectionFnBuilder` (under the
`model_connection` subpackage) defines the connection-side seam that
`otter-ai-assistant-provider-stream`'s `create_model_connection_by_provider`
implements (routing on `KnownApis` via the caller's `ProviderModelOption`).

The `otter-ai-core` package models LLM conversation context and the streaming
runtime used to build it. It defines **no LLMs, providers, APIs, transports,
API registry, or `stream()` dispatch** — only the Pydantic v2 data structures a
conversation is built from, plus a generic async stream runtime. The
assistant-message-stream **event protocol** (`AssistantMessageEvent` family)
and the **typed stream aliases** (`AssistantMessageStream` /
`AssistantMessageWriter` / the `AssistantMessageStreamFnBuilder` seam) live
under the `otter_ai_core.assistant_message_stream` subpackage, not the top
level.

- [`Context`](./packages/otter_ai_core/src/otter_ai_core/context.py) — the top-level
  conversation (`system_prompt`, `items`, `tools`), JSON-serializable so a
  context can be persisted and replayed elsewhere.
- [`ContextItem`](./packages/otter_ai_core/src/otter_ai_core/context_item.py) — the
  `{id, message}` wrapper layer between `Context` and `Message`. The `id` is
  caller/provider-supplied; it is **not** generated inside assistant message
  streams (e.g. Chat Completions).
- [`Message`](./packages/otter_ai_core/src/otter_ai_core/messages.py) — a discriminated
  union of `UserMessage`, `AssistantMessage`, and `ToolResultMessage`.
- Content blocks in `content.py`: `TextContent`, `ImageContent`,
  `ThinkingContent`, `ToolCall`.
- [`Tool`](./packages/otter_ai_core/src/otter_ai_core/tools.py) — tool definitions whose
  `parameters` accept a JSON-Schema `dict` or a Pydantic `BaseModel` subclass.
- [`Usage`](./packages/otter_ai_core/src/otter_ai_core/usage.py) and diagnostics for
  per-turn accounting.
- [`assistant_message_stream/`](./packages/otter_ai_core/src/otter_ai_core/assistant_message_stream/) — the
  streaming-event protocol: the `AssistantMessageEvent` family (a
  discriminated union on `type`), a port of pi-ai's assistant event protocol;
  plus the typed stream aliases. Imported from `otter_ai_core.assistant_message_stream`.
- [`stream.py`](./packages/otter_ai_core/src/otter_ai_core/stream.py) — a generic async
  stream runtime (`Stream` / `StreamWriter` / `create_stream`). See
  [Generic stream runtime](#generic-stream-runtime).

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
from otter_ai_core import Context, ContextItem, UserMessage, normalize_messages

context = Context(
    system_prompt="You are helpful.",
    items=[
        ContextItem(
            id="u1",
            message=UserMessage(role="user", content="Hi!", timestamp=0),
        )
    ],
)

# A Context round-trips through plain JSON.
restored = Context.model_validate_json(context.model_dump_json())
assert restored == context

# Opt-in replay prep (only when you intend to send to a model elsewhere):
replay_ready = normalize_messages([item.message for item in context.items])
```

### Generic stream runtime

[`stream.py`](./packages/otter_ai_core/src/otter_ai_core/stream.py) is a faithful
Python/`asyncio` port of pi-ai's `EventStream` push-queue. The runtime is split
into a consumer and a producer sharing one queue:

- `Stream[TEvent]` — the consumer; iterate with `async for`.
- `StreamWriter[TEvent]` — the producer; call `push(event)` for every event
  (including the terminal `done`/`error`), then `end()`.
- `create_stream()` — returns a `StreamWiring[TEvent]` whose `.producer` is
  the `StreamWriter` and `.consumer` is the `Stream`.

Typed aliases specialize it: `AssistantMessageStream` (and a matching
`AssistantMessageWriter`), with `AssistantMessageStreamFnBuilder` as the
producer-side seam type — all imported from
`otter_ai_core.assistant_message_stream`. There
is **no `result()`** — consumers read the terminal `done`/`error` event
directly.

`Stream` and `StreamWriter` are runtime objects and are **not** JSON-serializable
(unlike `Context`); the serializable data model is unchanged.

```python
import asyncio

from otter_ai_core import AssistantMessage, create_stream
from otter_ai_core.assistant_message_stream import AssistantDoneEvent


async def main() -> None:
    wiring = create_stream()
    stream = wiring.consumer
    writer = wiring.producer

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

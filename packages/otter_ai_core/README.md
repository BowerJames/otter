# otter-ai-core

**Otter AI** — a Pydantic v2 data model for representing LLM conversation
context, the streaming-event protocol used to build a single assistant message,
and the generic async runtimes (a one-way channel, an abortable stream facade,
and a bidirectional channel) plus the seam types a provider/transport package
will implement. No LLMs, providers, APIs, transports, API registry, or
`stream()` dispatch live here; only the data structures a conversation and an
event stream are built from, the runtimes that carry them, and the seams a
provider package will plug into.

The data shapes are a Python port of the models from
[`@earendil-works/pi-ai`](https://github.com/earendil-works/pi-ai).

## Install

This package lives in the `otter` uv workspace. From the repo root:

```bash
uv sync
```

Import it as `otter_ai_core`.

## Context model

A conversation is a [`Context`](./src/otter_ai_core/context/context.py): an
optional `system_prompt`, an `items` list, and optional `tools`. Everything is
pure-JSON-serializable so a context can be persisted, transferred, and replayed.

- [`ContextItem`](./src/otter_ai_core/context/context_item.py) — the `id`-tagged
  wrapper layer between `Context` and `Message`. Each item *is* a message (it
  inherits the message's fields directly) plus a caller/provider-supplied `id`;
  it is **not** generated inside assistant message streams. Build one with
  `context_item(message=..., id=...)` (or `XxxContextItem.from_message(...)`).
- [`Message`](./src/otter_ai_core/context/messages.py) — a discriminated union
  of `UserMessage`, `AssistantMessage`, `ToolResultMessage`.
- Content blocks in [`content.py`](./src/otter_ai_core/context/content.py):
  `TextContent`, `ImageContent`, `ThinkingContent`, `ToolCall`.
- [`Tool`](./src/otter_ai_core/context/tool.py) — `parameters` accepts a
  JSON-Schema `dict` or a Pydantic `BaseModel` subclass.
- [`Usage`](./src/otter_ai_core/context/usage.py) /
  [`diagnostics.py`](./src/otter_ai_core/context/diagnostics.py) for per-turn
  accounting and failure records.

`AssistantMessage` carries inert provenance (`api`, `provider`, `model`,
`response_model`, `response_id`) and accounting (`usage`, `stop_reason`,
`error_message`). Otter never interprets these — they are preserved so a
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

## Assistant message events

[`assistant_message_events.py`](./src/otter_ai_core/assistant_message_stream/assistant_message_events.py)
models the events emitted while an assistant message is being produced by an
LLM provider. It is the data-only event protocol; the transport that pushes
these events lives in a provider package.

A single discriminated union over `type`:

- [`AssistantMessageEvent`](./src/otter_ai_core/assistant_message_stream/assistant_message_events.py)
  — 12 events (a port of pi-ai): `start`, `text_start/delta/end`,
  `thinking_start/delta/end`, `tool_call_start/delta/end`, `done`, `error`.

### Terminal contract

A stream emits `start` first, then partial updates, and terminates with
**exactly one** of:

- `done` — the final message, with a `reason` (`"stop"` / `"length"` /
  `"tool_use"`, mirroring `stop_reason`).
- `error` — `reason` of `"error"` or `"aborted"`, with the final message (any
  partial content received before the failure is preserved on it).

Every non-terminal event carries a `partial` snapshot of the in-progress
message, so a consumer can render state from the latest event alone. Deltas are
associated with their block via `content_index`; events for different blocks
are **not** guaranteed to be contiguous.

### Quick example

```python
from pydantic import TypeAdapter

from otter_ai_core import AssistantMessage, AssistantMessageEvent

adapter = TypeAdapter(AssistantMessageEvent)

event = adapter.validate_json(payload)
match (event.role, event.type):
    case ("assistant", "text_delta"):
        print(event.delta, end="")
    case ("assistant", "done"):
        message: AssistantMessage = event.message  # the final message
    case ("assistant", "error"):
        # Aborted/errored run; event.error is the (partial) AssistantMessage.
        ...
```

## Runtimes

The package also owns the generic async runtimes the streaming events flow
through, plus the seam types a provider/transport package will implement:

- [`channel.py`](./src/otter_ai_core/channel.py) — a single-consumer async
  push-queue split into a read end and a write end
  (`ChannelReader` / `ChannelWriter` / `create_channel`).
- [`stream.py`](./src/otter_ai_core/stream.py) — an abortable stream facade
  layered over the channel (`StreamClient` / `StreamBackend` / `create_stream`);
  the abort signal is intrinsic to the stream, not threaded as an argument.
- [`bidirectional_channel.py`](./src/otter_ai_core/bidirectional_channel.py) — a
  bidirectional runtime for APIs that keep a live connection (Realtime /
  Responses) (`BidirectionalChannel` / `BidirectionalChannelBackend` /
  `create_bidirectional_channel`).
- [`builder.py`](./src/otter_ai_core/builder.py) — the generic
  `BuilderFn[TOptions, TResult]` alias both producer seams fold onto.
- [`hook.py`](./src/otter_ai_core/hook.py) — the generic async
  `Hook[TEvent, TResponse]` alias provider packages build hook types on top of.
- [`provider_api_model_options/`](./src/otter_ai_core/provider_api_model_options) —
  pure-data enumerations/types (`KnownApis`, `KnownProviders`,
  `ThinkingLevel`) a dispatch layer keys on.

See the [root `README.md`](../../README.md) for the full runtime documentation
and the producer-side seam types (`AssistantMessageStreamFnBuilder`,
`BidirectionalChannelFn`).

## Tooling

| Tool    | Purpose              | Config                              |
| ------- | -------------------- | ----------------------------------- |
| [ruff]  | Linting + formatting | `[tool.ruff]` in root `pyproject.toml` |
| [mypy]  | Static type checking | `[tool.mypy]` in root `pyproject.toml` |
| [pytest]| Testing              | `[tool.pytest.ini_options]`         |

[ruff]: https://docs.astral.sh/ruff/
[mypy]: https://mypy-lang.org/
[pytest]: https://docs.pytest.org/

# otter-ai

**Otter AI** — a data-only Pydantic v2 model for representing LLM conversation
context and the streaming events used to build it. No LLMs, providers, APIs,
transports, or `stream()` dispatch live here; only the data structures a
conversation and an event stream are built from.

The model is a Python port of the data shapes from
[`@earendil-works/pi-ai`](https://github.com/earendil-works/pi-ai), extended
with user and tool-result streaming event families.

## Install

This package lives in the `otter` uv workspace. From the repo root:

```bash
uv sync
```

Import it as `otter_ai`.

## Context model

A conversation is a [`Context`](./src/otter_ai/context.py): an optional
`system_prompt`, a `messages` list, and optional `tools`. Everything is
pure-JSON-serializable so a context can be persisted, transferred, and replayed.

- [`Message`](./src/otter_ai/messages.py) — discriminated union of
  `UserMessage`, `AssistantMessage`, `ToolResultMessage`.
- Content blocks in [`content.py`](./src/otter_ai/content.py):
  `TextContent`, `ImageContent`, `ThinkingContent`, `ToolCall`.
- [`Tool`](./src/otter_ai/tools.py) — `parameters` accepts a JSON-Schema `dict`
  or a Pydantic `BaseModel` subclass.
- [`Usage`](./src/otter_ai/usage.py) / [`diagnostics.py`](./src/otter_ai/diagnostics.py)
  for per-turn accounting and failure records.
- [`hook.py`](./src/otter_ai/hook.py) — the generic async
  `Hook[TEvent, TResponse]` alias provider packages build hook types on top of.

`AssistantMessage` carries inert provenance (`api`, `provider`, `model`,
`response_model`, `response_id`) and accounting (`usage`, `stop_reason`,
`error_message`). Otter never interprets these — they are preserved so a
context can be replayed by a provider package built on top.

### Opt-in replay normalization

[`normalize.py`](./src/otter_ai/normalize.py) exposes **opt-in** utilities that
prepare a message list for replay to a model:

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

## Streaming events

[`events.py`](./src/otter_ai/events.py) models the events emitted while a
context item is being produced — by an LLM provider (assistant content), a
realtime transcription API (user content), or a tool executor (tool results).
It is the data-only event protocol; the transport that pushes these events
lives in a future provider package.

Three per-role families, each a discriminated union over `type`:

- [`AssistantMessageEvent`](./src/otter_ai/events.py) — 12 events (a port of
  pi-ai): `start`, `text_start/delta/end`, `thinking_start/delta/end`,
  `tool_call_start/delta/end`, `done`, `error`.
- [`UserMessageEvent`](./src/otter_ai/events.py) — 6 events: `start`,
  `text_start/delta/end`, `done`, `error`.
- [`ToolResultMessageEvent`](./src/otter_ai/events.py) — 6 events (abortable):
  `start`, `text_start/delta/end`, `done`, `error`.
- [`ContextItemEvent`](./src/otter_ai/events.py) — the union of all three.

### Terminal contract

A stream emits `start` first, then partial updates, and terminates with
**exactly one** of:

- `done` — the final message. The assistant family carries a `reason`
  (`"stop"` / `"length"` / `"tool_use"`, mirroring `stop_reason`); user and
  tool-result `done` carry only the message.
- `error` — `reason` of `"error"` or `"aborted"`, with the final message (any
  partial content received before the failure is preserved on it).

Every non-terminal event carries a `partial` snapshot of the in-progress
message, so a consumer can render state from the latest event alone. Deltas are
associated with their block via `content_index`; events for different blocks
are **not** guaranteed to be contiguous.

### Two producer conventions (documented, not enforced)

- **Partials use the list form.** `UserMessage.content` is `str |
  list[UserContent]`; when streaming, producers build the `list` form so the
  `content_index` of every `*_delta`/`*_end` is well-defined.
- **Aborted tool results are marked.** An aborted tool-result partial carries
  `is_error=True` so it can be fed back to the model as an error. A `done`
  event may also carry `is_error=True` — that is a tool that *ran and returned
  an error* (a normal completion), distinct from an abort.

### Why `ContextItemEvent` is a plain union

Pydantic v2 requires each member of a discriminated union to map to a **unique**
discriminator value. All twelve assistant leaves share `role="assistant"`, so
discriminating `ContextItemEvent` on `role` is rejected, and a callable
composite-key discriminator only works on `TypedDict`, not `BaseModel`. The
plain-union-of-discriminated-unions form routes deterministically because every
leaf carries strict `role`/`type` Literals together with `extra="forbid"`.

### Quick example

```python
from pydantic import TypeAdapter

from otter_ai import ContextItemEvent

adapter = TypeAdapter(ContextItemEvent)

event = adapter.validate_json(payload)
match (event.role, event.type):
    case ("assistant", "text_delta"):
        print(event.delta, end="")
    case ("assistant", "done"):
        context.messages.append(event.message)
    case ("user", "done"):
        context.messages.append(event.message)
    case ("tool_result", "error"):
        # Aborted execution; event.error is a (partial) ToolResultMessage.
        context.messages.append(event.error)
```

## Tooling

| Tool    | Purpose              | Config                              |
| ------- | -------------------- | ----------------------------------- |
| [ruff]  | Linting + formatting | `[tool.ruff]` in root `pyproject.toml` |
| [mypy]  | Static type checking | `[tool.mypy]` in root `pyproject.toml` |
| [pytest]| Testing              | `[tool.pytest.ini_options]`         |

[ruff]: https://docs.astral.sh/ruff/
[mypy]: https://mypy-lang.org/
[pytest]: https://docs.pytest.org/

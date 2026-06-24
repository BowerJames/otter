# otter-ai-core

**Otter AI** — a data-only Pydantic v2 model for representing LLM conversation
context and the streaming events used to build it. No LLMs, providers, APIs,
transports, or `stream()` dispatch live here; only the data structures a
conversation and an event stream are built from.

The model is a Python port of the data shapes from
[`@earendil-works/pi-ai`](https://github.com/earendil-works/pi-ai).

## Install

This package lives in the `otter` uv workspace. From the repo root:

```bash
uv sync
```

Import it as `otter_ai_core`.

## Context model

A conversation is a [`Context`](./src/otter_ai_core/context.py): an optional
`system_prompt`, a `messages` list, and optional `tools`. Everything is
pure-JSON-serializable so a context can be persisted, transferred, and replayed.

- [`Message`](./src/otter_ai_core/messages.py) — discriminated union of
  `UserMessage`, `AssistantMessage`, `ToolResultMessage`.
- Content blocks in [`content.py`](./src/otter_ai_core/content.py):
  `TextContent`, `ImageContent`, `ThinkingContent`, `ToolCall`.
- [`Tool`](./src/otter_ai_core/tools.py) — `parameters` accepts a JSON-Schema `dict`
  or a Pydantic `BaseModel` subclass.
- [`Usage`](./src/otter_ai_core/usage.py) / [`diagnostics.py`](./src/otter_ai_core/diagnostics.py)
  for per-turn accounting and failure records.
- [`hook.py`](./src/otter_ai_core/hook.py) — the generic async
  `Hook[TEvent, TResponse]` alias provider packages build hook types on top of.

`AssistantMessage` carries inert provenance (`api`, `provider`, `model`,
`response_model`, `response_id`) and accounting (`usage`, `stop_reason`,
`error_message`). Otter never interprets these — they are preserved so a
context can be replayed by a provider package built on top.

### Opt-in replay normalization

[`normalize.py`](./src/otter_ai_core/normalize.py) exposes **opt-in** utilities that
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

## Assistant message events

[`assistant_message_events.py`](./src/otter_ai_core/assistant_message_events.py) models the events emitted while an
assistant message is being produced by an LLM provider. It is the data-only
event protocol; the transport that pushes these events lives in a provider
package.

A single discriminated union over `type`:

- [`AssistantMessageEvent`](./src/otter_ai_core/assistant_message_events.py) — 12 events (a port of
  pi-ai): `start`, `text_start/delta/end`, `thinking_start/delta/end`,
  `tool_call_start/delta/end`, `done`, `error`.

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

from otter_ai_core import AssistantMessageEvent

adapter = TypeAdapter(AssistantMessageEvent)

event = adapter.validate_json(payload)
match (event.role, event.type):
    case ("assistant", "text_delta"):
        print(event.delta, end="")
    case ("assistant", "done"):
        context.messages.append(event.message)
    case ("assistant", "error"):
        # Aborted/errored run; event.error is the (partial) AssistantMessage.
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

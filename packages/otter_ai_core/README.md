# otter-ai-core

**Otter AI** — a Pydantic v2 data model for representing LLM conversation
context, plus the generic async runtimes and seam types a provider/transport
package will implement. No LLMs, providers, APIs, transports, API registry, or
`stream()` dispatch live here; only the data structures a conversation is built
from, the runtimes that carry them, and the seams a provider package will plug
into.

The data shapes are a Python port of the models from
[`@earendil-works/pi-ai`](https://github.com/earendil-works/pi-ai).

## Install

This package lives in the `otter` uv workspace. From the repo root:

```bash
uv sync
```

Import it as `otter_ai_core`.

## Package shape — four buckets

The top level of `src/otter_ai_core/` is exactly four role-named buckets plus a
frozen re-export facade (`__init__.py`). Dependencies flow one way along the
layering DAG `data_models ← interfaces ← {mixins, runtime}` — no cycles:

- [`data_models/`](./src/otter_ai_core/data_models) — **pure data** (pydantic
  models, enums, discriminated unions, type aliases). Depends on nothing
  internal. Domain-grouped:
  - [`context/`](./src/otter_ai_core/data_models/context) — the conversation
    context model (content blocks, messages, items, tool, usage, diagnostics,
    role).
  - [`provider/`](./src/otter_ai_core/data_models/provider) — pure-data
    enumerations/types (`KnownApis`, `KnownProviders`,
    `ProviderModelOption`, `ThinkingLevel`) a dispatch layer keys on.
  - [`session/`](./src/otter_ai_core/data_models/session) — the persisted
    session entry model, metadata, errors, and the projection *result types*
    (`SessionProjection`, `SessionDerivedState`).
  - [`events/`](./src/otter_ai_core/data_models/events) — the transient event
    signals: the `Event[T]` base, the model-connection client/server context
    events, and the session-store event types/payloads.
  - [`agent_tool.py`](./src/otter_ai_core/data_models/agent_tool.py) —
    `AgentToolResult`, loose at the bucket root as a recognized orphan (the
    tool-execution envelope, context-*adjacent* rather than conversation state).
- [`interfaces/`](./src/otter_ai_core/interfaces) — **public Protocols** (flat):
  the streaming/connection/channel seams, `ModelController`, `SessionStore`,
  `AgentTool`, `TaskRunner`, etc. Depends only on `data_models/`.
- [`mixins/`](./src/otter_ai_core/mixins) — **shared-behavior concrete MixIns**
  (flat); first occupant `TaskRunnerMixIn` (the `@final` async lifecycle MixIn).
- [`runtime/`](./src/otter_ai_core/runtime) — **concrete executing code**,
  classes *and* free functions:
  - [`bus.py`](./src/otter_ai_core/runtime/bus.py) /
    [`default_channel.py`](./src/otter_ai_core/runtime/default_channel.py) — the
    descriptor-validated pub/sub `Bus` and its queue-based default `Channel`.
  - [`default_model_controller/`](./src/otter_ai_core/runtime/default_model_controller)
    — the default `ModelController` implementation + its `State` latch.
  - [`session/`](./src/otter_ai_core/runtime/session) — `SessionStoreController`
    and the projection *pure functions* (`project`, `derive_state`,
    `apply_compaction_transform`, `apply_updates`, `entries_to_items`), mirroring
    `data_models/session/`.

The frozen top-level facade `from otter_ai_core import …` is preserved (only
removals of evicted symbols are permitted).

## Context model

A conversation is a [`Context`](./src/otter_ai_core/data_models/context/context.py):
an optional `system_prompt`, an `items` list, and optional `tools`. Everything is
pure-JSON-serializable so a context can be persisted, transferred, and replayed.

- [`ContextItem`](./src/otter_ai_core/data_models/context/context_item.py) — the
  `{id, message}` wrapper layer between `Context` and `Message`. Each item
  *wraps* a message plus a caller/provider-supplied `id`; it is **not** generated
  inside assistant message streams. Build one with `context_item(message=...,
  id=...)` (or `XxxContextItem(id=..., message=...)`).
- [`Message`](./src/otter_ai_core/data_models/context/messages.py) — a
  discriminated union of `UserMessage`, `AssistantMessage`, `ToolResultMessage`.
- Content blocks in
  [`content.py`](./src/otter_ai_core/data_models/context/content.py):
  `TextContent`, `ImageContent`, `ThinkingContent`, `ToolCall`.
- [`Tool`](./src/otter_ai_core/data_models/context/tool.py) — `parameters`
  accepts a JSON-Schema `dict` or a Pydantic `BaseModel` subclass.
- [`Usage`](./src/otter_ai_core/data_models/context/usage.py) /
  [`diagnostics.py`](./src/otter_ai_core/data_models/context/diagnostics.py) for
  per-turn accounting and failure records.

`AssistantMessage` carries inert provenance (`api`, `provider`, `model`,
`response_model`, `response_id`) and accounting (`usage`, `stop_reason`,
`error_message`). Otter never interprets these — they are preserved so a context
can be replayed by a provider package built on top.

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

## Runtimes

The package owns the generic async runtimes the streaming events flow through,
plus the seam types a provider/transport package will implement:

- [`bus.py`](./src/otter_ai_core/runtime/bus.py) — a name-keyed pub/sub bus. Each
  event name is registered with the concrete payload class every emitted event
  must be an instance of (validated at `emit` time); `on`/`emit` fan each payload
  out to every subscriber (handler exceptions isolated and logged). It reuses
  `TaskRunnerMixIn` for its drain worker lifecycle.
- [`default_channel.py`](./src/otter_ai_core/runtime/default_channel.py) — a
  single-consumer async push-queue implementing the `Channel` Protocol, with an
  intrinsic end-of-stream sentinel.

## Default model controller

[`default_model_controller/`](./src/otter_ai_core/runtime/default_model_controller)
turns a low-level connection conduit into a stateful conversation. It is the
default implementation of the `ModelController` Protocol (defined in
[`interfaces/model_controller.py`](./src/otter_ai_core/interfaces/model_controller.py))
and is re-exported at the top level (`DefaultModelController` / `State`) — the
high-level convenience most callers want.

- [`DefaultModelController`](./src/otter_ai_core/runtime/default_model_controller/controller.py)
  — wraps an `AbortableConnection[ServerContextEvent, ClientContextEvent]`,
  drives the conversation via **async, confirmation-awaiting commands**
  (`add_message` / `generate` / `compact` / `branch` / `abort`), tracks idle/busy
  state within each command method (busy on push, idle when its confirmation
  event arrives), and re-publishes every server event to its `Bus`. Subscribe
  via the `ServerContextEventType` members in
  [`data_models/events/server_context_events.py`](./src/otter_ai_core/data_models/events/server_context_events.py)
  (`RESPONSE_DONE`, `USER_ITEM_ADDED`, …).
- [`State`](./src/otter_ai_core/runtime/default_model_controller/state.py) — the
  idle/busy `asyncio.Event` latch plus an `is_closing` flag.

A fresh controller starts **idle**. Stage input with one or more
`await add_message(...)` calls (each awaits the server's `user_item.added` /
`tool_result_item.added` echo), then `await generate()` to request and await the
next assistant response (it returns the echoed assistant item on
`response.done`). Commands are single-flight (rejected while busy) and never
hang: if the run loop exits before the awaited confirmation arrives — teardown,
or a non-conformant backend — the command raises rather than stranding its task.
Two distinct aborts:

- `abort()` — **protocol** abort: stop the in-flight generation but keep the
  connection open (pushes an `AbortResponse`).
- `close()` / `aclose()` — **runtime** teardown: tear the connection down via
  `client.abort()`.

Prefer `async with DefaultModelController(client)`.

## Session layer

The persisted, restorable, observable per-session layer splits data from logic
across the `data_models/session/` and `runtime/session/` buckets:

- [`SessionStore`](./src/otter_ai_core/interfaces/store.py) — the Protocol a
  session backend implements (append-only entry log, leaf pointer, path reads).
- [`SessionStoreController`](./src/otter_ai_core/runtime/session/controller.py)
  — the concrete controller over a `SessionStore`: serializes writes, projects
  the active branch to a `Context`, and fans session events out over its owned
  `Bus` (keyed on the `SessionStoreControllerEventTypes` names).
- Session entries / metadata / errors live in
  [`data_models/session/`](./src/otter_ai_core/data_models/session); the
  projection *pure functions* (`project`, `derive_state`,
  `apply_compaction_transform`, `apply_updates`, `entries_to_items`) and their
  *result types* (`SessionProjection`, `SessionDerivedState`) split by kind —
  functions in `runtime/session/`, result types in `data_models/session/`.

See the [root `README.md`](../../README.md) for the full runtime documentation.

## Tooling

| Tool    | Purpose              | Config                                  |
| ------- | -------------------- | --------------------------------------- |
| [ruff]  | Linting + formatting | `[tool.ruff]` in root `pyproject.toml`  |
| [mypy]  | Static type checking | `[tool.mypy]` in root `pyproject.toml`  |
| [pytest]| Testing              | `[tool.pytest.ini_options]`             |

[ruff]: https://docs.astral.sh/ruff/
[mypy]: https://mypy-lang.org/
[pytest]: https://docs.pytest.org/

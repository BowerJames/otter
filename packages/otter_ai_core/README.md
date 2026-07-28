# otter-ai-core

**Otter AI** — a Pydantic v2 data model for representing LLM conversation
context, and the generic async runtimes (a one-way channel, an abortable stream
facade, a bidirectional channel, and a typed event bus) plus the seam types a
provider/transport package will implement. No LLMs, providers, APIs,
transports, API registry, or `stream()` dispatch live here; only the data
structures a conversation is built from, the runtimes that carry them, and the
seams a provider package will plug into.

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

- [`ContextItem`](./src/otter_ai_core/context/context_item.py) — the `{id, message}`
  wrapper layer between `Context` and `Message`. Each item *wraps* a message
  plus a caller/provider-supplied `id`; it is **not** generated inside assistant
  message streams. Build one with `context_item(message=..., id=...)`
  (or `XxxContextItem(id=..., message=...)`).
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

## Runtimes

The package also owns the generic async runtimes the streaming events flow
through, plus the seam types a provider/transport package will implement:

- [`channel.py`](./src/otter_ai_core/channel.py) — a single-consumer async
  push-queue split into a read end and a write end
  (`ChannelReader` / `ChannelWriter` / `create_channel`).
- [`bus.py`](./src/otter_ai_core/bus.py) — a descriptor-keyed pub/sub bus.
  Its key is a typed `BusEvent[TPayload]` descriptor (the fan-out counterpart
  to `Hook`/`HookRunner`); `subscribe`/`publish` infer `TPayload` per call, so
  the public API is fully type-safe and the set of events is open. The bus
  retains its queue + worker and fans each published payload out to every
  subscriber of its descriptor (handler exceptions isolated and logged).
- [`stream.py`](./src/otter_ai_core/stream.py) — an abortable one-way stream
  facade layered over the channel (`StreamClient` / `StreamBackend` /
  `create_stream`); the abort signal is intrinsic to the stream, not threaded
  as an argument.
- [`bidirectional_channel.py`](./src/otter_ai_core/bidirectional_channel.py) — a
  bidirectional queue primitive (two cross-wired channels) for APIs that keep
  a live connection (Realtime / Responses) (`BidirectionalChannelClient` /
  `BidirectionalChannelBackend` / `BidirectionalChannelPair` /
  `create_bidirectional_channel`).
- [`connection.py`](./src/otter_ai_core/connection.py) — an abortable
  bidirectional facade layered over the bidirectional channel
  (`ConnectionClient` / `ConnectionBackend` / `ConnectionPair` /
  `create_connection`) — a two-way consumer handle that can iterate, push, and
  abort; the bidirectional peer of `stream.py`.
- [`builder.py`](./src/otter_ai_core/builder.py) — the generic
  `BuilderFn[TOptions, TResult]` alias a producer seam folds onto.
- [`provider_api_model_options/`](./src/otter_ai_core/provider_api_model_options) —
  pure-data enumerations/types (`KnownApis`, `KnownProviders`,
  `ThinkingLevel`) a dispatch layer keys on.

The model-connection event protocol (`ClientContextEvent` /
`ServerContextEvent`) and the typed two-way connection aliases
(`ModelConnectionClient` / `ModelConnectionBackend`) live in
[`model_connection/`](./src/otter_ai_core/model_connection). The high-level
conversation driver layered over a `ModelConnectionClient` — `ModelController`
and `State` — lives in
[`model_controller/`](./src/otter_ai_core/model_controller) and is documented
below.

## Model controller

[`model_controller/`](./src/otter_ai_core/model_controller) turns the low-level
connection conduit into a stateful conversation. It is re-exported at the top
level (`ModelController` / `State`) — the high-level convenience most callers
want, unlike the subpackage-only `model_connection`.

- [`ModelController`](./src/otter_ai_core/model_controller/controller.py) —
  wraps a `ModelConnectionClient`, drives the conversation via **async,
  confirmation-awaiting commands** (`add_message` / `generate` / `abort`),
  tracks idle/busy state within each command method (busy on push, idle when
  its confirmation event arrives), and re-publishes every server event to its
  `bus` (a descriptor-keyed
  [`Bus`](./src/otter_ai_core/bus.py)). Subscribe via the per-variant
  `BusEvent` descriptors in
  [`interfaces/model_controller.py`](./src/otter_ai_core/interfaces/model_controller.py)
  (`RESPONSE_DONE`, `USER_ITEM_ADDED`, …), built from the
  `ModelControllerEventTypes` `StrEnum`.
- [`State`](./src/otter_ai_core/model_controller/state.py) — the idle/busy
  `asyncio.Event` latch plus a `is_closing` flag.

A fresh controller starts **idle**. Stage input with one or more
`await add_message(...)` calls (each awaits the server's `user_item.added` /
`tool_result_item.added` echo), then `await generate()` to request and await
the next assistant response (it returns the echoed assistant item on
`response.done`). Both commands
are single-flight (rejected while busy) and never hang: if the run loop exits
before the awaited confirmation arrives — teardown, or a non-conformant backend
— the command raises rather than stranding its task. Two distinct aborts:

- `abort()` — **protocol** abort: stop the in-flight generation but keep the
  connection open (pushes an `AbortResponse`).
- `close()` / `aclose()` — **runtime** teardown: tear the connection down via
  `client.abort()`.

Teardown is cooperative first, deterministic second. `close()` is synchronous
and only *initiates* teardown (`client.abort()`); the controller keeps draining
so a conformant backend's shutdown items still flow through the bus.
`aclose(timeout)` awaits that drain to completion and force-cancels if a
wedged backend never ends the inbound — so no owned task is left pending.
Prefer `async with ModelController(client)` (or `await controller.aclose()`).

### Quick example

The example shows the **consumer** side only. In practice a transport /
provider task pumps `pair.backend` — pushing `ServerContextEvent`s and draining
`ClientContextEvent`s — otherwise `generate()` will never return.

```python
import asyncio

from otter_ai_core import ModelController, UserMessage, create_connection
from otter_ai_core.context import Role
from otter_ai_core.model_connection import AddUserMessage


async def main() -> None:
    pair = create_connection()  # a transport task pumps pair.backend in practice
    async with ModelController(pair.client) as controller:
        # Stage input. Each call awaits the server's item-added echo and
        # returns the echoed item (carrying the server-assigned id).
        user_item = await controller.add_message(
            AddUserMessage(
                message=UserMessage(role=Role.User, content="Hi!", timestamp=0)
            )
        )
        # ...then request and await the next assistant response. Returns the
        # echoed final assistant item (carrying the server-assigned id).
        assistant_item = await controller.generate()  # returns on response.done


asyncio.run(main())
```

See the [root `README.md`](../../README.md) for the full runtime documentation.

## Tooling

| Tool    | Purpose              | Config                              |
| ------- | -------------------- | ----------------------------------- |
| [ruff]  | Linting + formatting | `[tool.ruff]` in root `pyproject.toml` |
| [mypy]  | Static type checking | `[tool.mypy]` in root `pyproject.toml` |
| [pytest]| Testing              | `[tool.pytest.ini_options]`         |

[ruff]: https://docs.astral.sh/ruff/
[mypy]: https://mypy-lang.org/
[pytest]: https://docs.pytest.org/

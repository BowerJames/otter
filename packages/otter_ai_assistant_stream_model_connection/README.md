# otter-ai-assistant-stream-model-connection

Pure-local adapter that wraps an
[`AssistantMessageStreamFn`](../otter_ai_core/src/otter_ai_core/assistant_message_stream/assistant_message_stream.py)
as a fully-functional, request-driven
[`ModelConnectionFn`](../otter_ai_core/src/otter_ai_core/model_connection/model_connection.py)
for `otter-ai-core`.

## Scope

This package owns a single seam,
`create_assistant_stream_model_connection`, a concrete value of
[`ModelConnectionFnBuilder[AssistantMessageStreamFn]`](../otter_ai_core/src/otter_ai_core/model_connection/model_connection.py).
It is a **pure-local adapter** — no transport, provider, registry, or dispatch. A
provider that can already produce an `AssistantMessageStream` per turn (e.g. a
chat-completions stream or a provider-stream dispatch) can be surfaced through the
*connection* protocol (the bidirectional peer of the stream protocol) without
speaking a realtime wire format: the supplied `stream_fn` runs locally as the
backend.

It is the connection-side **peer** of
[`otter-ai-chat-completions`](../otter_ai_chat_completions) /
[`otter-ai-assistant-provider-stream`](../otter_ai_assistant_provider_stream):
those are `AssistantMessageStreamFnBuilder` values; this adapts any such value into a
`ModelConnectionFnBuilder` value.

## Install

Part of the otter uv workspace (see the root `README.md`). The workspace globs
`packages/*`, so `uv sync` picks this package up automatically.

## Quick example

```python
import asyncio

from otter_ai_core import Context, UserMessage
from otter_ai_core.assistant_message_stream import AssistantMessageStreamFn
from otter_ai_assistant_stream_model_connection import (
    create_assistant_stream_model_connection,
)

# Any AssistantMessageStreamFn — e.g. a chat-completions builder's output, or a
# provider-stream dispatch: `create_assistant_message_stream_by_provider(options)`.
stream_fn: AssistantMessageStreamFn = ...  # producer(context, abort) -> AssistantMessageStream

# A builder: closes over stream_fn and returns the bound ModelConnectionFn.
connection_fn = create_assistant_stream_model_connection(stream_fn)

context = Context(
    system_prompt="You are helpful.",
    items=[],  # items=[ContextItem(...)] in the current API
)

# Open the connection (synchronous, never raises; spawns its backend).
conn = connection_fn(context, asyncio.Event())


async def consume() -> None:
    # Drive a generation: send response.create, iterate the server events.
    from otter_ai_core.model_connection import ResponseCreate

    conn.send(ResponseCreate(type="response.create"))
    async for event in conn:
        ...  # ResponseStartedEvent, ResponseText*Event, ResponseDoneEvent, ...


asyncio.run(consume())
```

## Driver semantics

* **Request-driven / multi-turn.** The backend idles, draining client events. On a
  `ResponseCreate` it invokes `stream_fn(context, per_response_abort)` once for that
  turn and forwards the translated `ServerEvent`s. A subsequent `ResponseCreate`
  starts the next generation.
* **Live context.** A client `ContextItemAddEvent` appends to the caller's
  `Context` (mutated in place) and echoes a `ContextItemAddedEvent`. On a clean
  `AssistantDoneEvent` the final message is auto-appended as an `AssistantContextItem`
  (fresh `uuid4` id) and announced — the local equivalent of a Realtime server's
  `conversation.item.created` after `response.done`.
* **Per-response abort.** A client `AbortResponseEvent` aborts **only** the
  in-flight response (via a fresh `per_response_abort` `asyncio.Event` passed into
  `stream_fn`); the connection stays open for further generations.
* **Connection cancel.** The producer's required `abort` argument is a
  *connection*-level cancel: setting it aborts any in-flight response and ends the
  connection gracefully (no `ConnectionErrorEvent`). Caller `close()` behaves
  identically.

Erred/aborted responses are **not** appended to the context (they are unreplayable —
see `otter_ai_core.normalize`).

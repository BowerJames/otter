# otter-ai-chat-completions

Chat Completions wire-format **contract** package for `otter-ai`.

## Scope

This package owns the Chat Completions wire-format contract: the data model
(`ChatCompletionsModel`), the runtime options bundle, and the seam
`create_chat_completions_assistant_message_stream` — a concrete
implementation of `otter_ai.AssistantMessageStreamFn`.

It is **provider-agnostic by design**: it performs no provider/base_url
detection, no env-key resolution, and ships no model catalog.
Provider-specific configuration (compat flags, static headers, env keys,
the models.dev catalog) is the **consumer's** responsibility.

> **Status:** this initial version delivers the type layer + seam signature.
> The stream body raises `NotImplementedError`; translation, httpx transport,
> and behavioural tests land in a follow-on PR.

## Install

Part of the otter uv workspace (see the root `README.md`). The workspace
globs `packages/*`, so `uv sync` picks this package up automatically.

## Quick example

```python
import asyncio

from otter_ai import Context, UserMessage
from otter_ai_chat_completions import (
    ChatCompletionsCost,
    ChatCompletionsModel,
    ChatCompletionsModelOptions,
    create_chat_completions_assistant_message_stream,
)

model = ChatCompletionsModel(
    id="gpt-4o",
    name="GPT-4o",
    provider="openai",
    base_url="https://api.openai.com/v1",
    reasoning=False,
    input_modalities=["text", "image"],
    context_window=128_000,
    max_tokens=16_384,
    cost=ChatCompletionsCost(input=2.5, output=10.0, cache_read=1.25, cache_write=0.0),
    api_key="sk-...",          # or leave None and resolve env in the consumer
)

options = ChatCompletionsModelOptions(model=model)

context = Context(
    system_prompt="You are helpful.",
    messages=[UserMessage(role="user", content="Hi!", timestamp=0)],
)

stream = create_chat_completions_assistant_message_stream(options, context)


async def consume() -> None:
    async for event in stream:
        ...


asyncio.run(consume())
```

## Per-call mutation

The serializable request config lives on `ChatCompletionsModel`. Override it
per call with `model_copy`:

```python
chatty_options = ChatCompletionsModelOptions(
    model=model.model_copy(update={"temperature": 0.9, "request_max_tokens": 512}),
)
```

## Hooks

`on_payload` (mutator, pre-send; non-`None` return replaces the body) and
`on_response` (observer, post-headers; narrow `{status, headers}` view). Both
async-only. See `hooks.py`.

## Abort

Cooperative via `options.abort_signal: asyncio.Event`. The future transport
checks `is_set()` between SSE chunks and emits an `AssistantErrorEvent` with
`reason="aborted"` when set.

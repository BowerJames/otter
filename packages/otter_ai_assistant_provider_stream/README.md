# otter-ai-assistant-provider-stream

Provider/dispatch layer for `otter-ai`.

## Scope

This package owns the **dispatch layer** that `otter-ai` deliberately omits:
a built-in model catalog (generated from [models.dev]), env-key resolution,
thinking-level clamping, three runtime registries, and the seam
`create_assistant_message_stream_by_provider` — a concrete value of
`otter_ai.AssistantMessageStreamFn`.

It dispatches through [`otter-ai-chat-completions`](../otter_ai_chat_completions);
a future provider package registers additional api stream fns without this
package changing.

It is loosely based on the dispatch (`api-registry.ts` + `stream.ts`),
env-key (`env-api-keys.ts`), model catalog (`models.ts` + `models.generated.ts`),
and thinking-clamp (`models.ts`) layers of `@earendil-works/pi-ai`.

[models.dev]: https://models.dev
[`otter-ai-chat-completions`]: ../otter_ai_chat_completions

## Install

Part of the otter uv workspace (see the root `README.md`). The workspace globs
`packages/*`, so `uv sync` picks this package up automatically.

## Built-in providers

```python
from otter_ai_assistant_provider_stream import BUILT_IN_PROVIDERS

BUILT_IN_PROVIDERS == ["zai", "openai"]
```

Both route through Chat Completions:

* **openai** — `https://api.openai.com/v1`, standard (all-default) compat.
  (pi-ai emits OpenAI models with `api="openai-responses"`; otter has only the
  chat-completions seam today, so the generator overrides it.)
* **zai** — `https://api.z.ai/api/coding/paas/v4`, `thinking_format="zai"`,
  with the glm-5.2 `thinking_level_map` and per-model `zai_tool_stream` flags
  carried over verbatim from pi-ai.

The catalog is generated from `https://models.dev/api.json` by
`scripts/generate_models.py` (run on demand; no runtime network) into a
committed `_catalog_generated.py`. Regenerate with:

```bash
uv run python packages/otter_ai_assistant_provider_stream/scripts/generate_models.py
```

## Quick example

```python
import asyncio

from otter_ai import Context, UserMessage
from otter_ai_assistant_provider_stream import (
    ModelProviderConfig,
    ModelProviderOptions,
    create_assistant_message_stream_by_provider,
)

# API key resolved from ZAI_API_KEY unless api_key is set explicitly.
options = ModelProviderOptions(
    model=ModelProviderConfig(model="glm-5.2", provider="zai", api_key="sk-...")
)
context = Context(
    system_prompt="You are helpful.",
    messages=[UserMessage(role="user", content="Hi!", timestamp=0)],
)
stream = create_assistant_message_stream_by_provider(options, context)


async def consume() -> None:
    async for event in stream:
        ...


asyncio.run(consume())
```

The seam is synchronous, returns the `AssistantMessageStream` immediately, and
**never raises** — unknown model/api or a missing API key is encoded as an
`AssistantErrorEvent` on the returned stream (mirrors pi-ai's
`createLazyLoadErrorMessage`).

## Config

```python
from otter_ai_assistant_provider_stream import (
    ModelProviderConfig,
    ModelProviderOverrides,
)

ModelProviderConfig(
    model="glm-5.2",
    provider="zai",
    api="chat-completions",     # default; the dispatch key
    thinking_level="low",       # default; clamped against the model's levels
    api_key=None,               # explicit key; else env var; else error event
    overrides=None,             # ModelProviderOverrides, see below
)

ModelProviderOverrides(
    temperature=0.9,
    request_max_tokens=512,
    base_url="https://proxy.test/v1",
    # ...and every other ChatCompletionsModel request field.
    # `compat` is field-merged onto the catalog compat (caller wins per-field).
)
```

## Env-key resolution

Explicit `api_key` > env var > raise (encoded as an error event):

| Provider | Env var          |
| -------- | ---------------- |
| `openai` | `OPENAI_API_KEY` |
| `zai`    | `ZAI_API_KEY`    |

Registered providers declare their own `env_key` on their `ProviderConfig`.

## Thinking levels

`ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh"`
(pi-ai `ModelThinkingLevel`); default `"low"`. A requested level is clamped
against the model's supported levels (derived from `reasoning` +
`thinking_level_map`) via a faithful port of pi-ai's `clampThinkingLevel`.
`"off"` maps to no `reasoning_effort`; the provider-specific mapping (via
`thinking_level_map`) is applied downstream by `otter_ai_chat_completions`.

## Runtime registries

Three registries, all seedable/overridable at runtime, mirror pi-ai:

* **Providers** — `register_provider` / `get_provider` (`ProviderConfig`).
* **Model catalog** — `register_model` / `get_model`
  (`ChatCompletionsModel`, keyed `(provider, id)`).
* **Api stream fns** — `register_api_stream_fn` / `get_api_stream_fn`,
  seeded with `"chat-completions"` → the chat-completions seam.

`reset()` clears all three and re-registers built-ins only.

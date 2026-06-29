"""The seam's first argument: model + runtime handles."""

from __future__ import annotations

from dataclasses import dataclass, field

from otter_ai_chat_completions.hooks import ChatCompletionsHooks
from otter_ai_chat_completions.models import ChatCompletionsModel


@dataclass
class ChatCompletionsModelOptions:
    """Bundle passed to the stream-function builder.

    Combines the pure-data :class:`ChatCompletionsModel` with runtime handles
    (hooks) that cannot live on a serializable Pydantic model. This bundle is
    the builder's sole argument; the builder is a value of
    ``AssistantMessageStreamFnBuilder[ChatCompletionsModelOptions]``. This
    bundle realises
    :data:`otter_ai_core.assistant_message_stream.AssistantMessageStreamFnBuilder`'s
    ``TOptions``.

    The builder closes over this bundle and returns an
    ``AssistantMessageStreamFn``; the context and the abort signal (an
    :class:`asyncio.Event`) are supplied when that returned function is
    invoked. The abort signal is **not** part of this bundle: it is the single
    source of truth for cooperative abort. ``hooks`` defaults to an empty
    :class:`ChatCompletionsHooks` (no-op), so a "no hooks" caller constructs
    this with just the model.
    """

    model: ChatCompletionsModel
    hooks: ChatCompletionsHooks = field(default_factory=ChatCompletionsHooks)

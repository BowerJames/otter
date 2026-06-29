"""The seam's first argument: model + runtime handles."""

from __future__ import annotations

from dataclasses import dataclass, field

from otter_ai_chat_completions.hooks import ChatCompletionsHooks
from otter_ai_chat_completions.models import ChatCompletionsModel


@dataclass
class ChatCompletionsModelOptions:
    """Bundle passed to the stream function.

    Combines the pure-data :class:`ChatCompletionsModel` with runtime handles
    (hooks) that cannot live on a serializable Pydantic model. This bundle is
    the seam's first argument; the stream function is a value of
    ``AssistantMessageStreamFnBuilder[ChatCompletionsModelOptions]``. This
    bundle realises
    :data:`otter_ai_core.assistant_message_stream.AssistantMessageStreamFnBuilder`'s
    ``TOptions``.

    The abort signal is **not** part of this bundle: it is supplied as the
    seam's third argument (an :class:`asyncio.Event`) and is the single source
    of truth for cooperative abort. ``hooks`` defaults to an empty
    :class:`ChatCompletionsHooks` (no-op), so a "no hooks" caller constructs
    this with just the model.
    """

    model: ChatCompletionsModel
    hooks: ChatCompletionsHooks = field(default_factory=ChatCompletionsHooks)

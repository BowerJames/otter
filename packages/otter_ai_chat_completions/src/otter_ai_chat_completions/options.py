"""The seam's first argument: model + runtime handles."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from otter_ai_chat_completions.hooks import ChatCompletionsHooks
from otter_ai_chat_completions.models import ChatCompletionsModel


@dataclass
class ChatCompletionsModelOptions:
    """Bundle passed to the stream function.

    Combines the pure-data :class:`ChatCompletionsModel` with runtime handles
    (hooks, abort signal) that cannot live on a serializable Pydantic model.
    This bundle is the seam's first argument; the stream function is a value
    of ``AssistantMessageStreamFn[ChatCompletionsModelOptions]``. This bundle
    realises :data:`otter_ai_core.AssistantMessageStreamFn`'s ``TOptions`` — the
    realistic shape for a provider whose per-call configuration includes
    runtime handles (hooks, abort signal) alongside the pure-data model.

    ``hooks`` defaults to an empty :class:`ChatCompletionsHooks` (no-op) and
    ``abort_signal`` defaults to a fresh, unset :class:`asyncio.Event`, so a
    "no hooks / no explicit abort" caller constructs this with just the model.
    The future transport layer checks ``abort_signal.is_set()`` between SSE
    chunks (cooperative abort).
    """

    model: ChatCompletionsModel
    hooks: ChatCompletionsHooks = field(default_factory=ChatCompletionsHooks)
    abort_signal: asyncio.Event = field(default_factory=asyncio.Event)

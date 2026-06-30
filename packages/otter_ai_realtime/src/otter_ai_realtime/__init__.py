"""otter-ai-realtime — Realtime wire-format contract package.

Defines the data model (:class:`RealtimeModel`, :class:`RealtimeCost`,
:class:`RealtimeSessionConfig`), the runtime options bundle
(:class:`RealtimeModelOptions` = model + session config + hooks), and the
seam :func:`create_realtime_model_connection` — a concrete implementation of
:data:`otter_ai_core.model_connection.ModelConnectionFnBuilder` (parameterised
by :class:`RealtimeModelOptions`) for OpenAI-Realtime-format APIs (a WebSocket
transport with ``session.update`` /
``conversation.item.create`` / ``response.*`` events).

The package is **generic**: it covers any provider that follows the OpenAI
Realtime API wire format, not OpenAI specifically — mirroring how
:mod:`otter_ai_chat_completions` covers general chat-completions APIs.

Scope: this package owns the realtime wire-format contract + the WebSocket
transport pump only. Provider-specific configuration (base URL, headers, env-
key resolution, model catalog) is the consumer's responsibility. v1 is
**text-only** — audio modalities are a tracked follow-up.

The seam is the **bidirectional peer** of
:func:`otter_ai_chat_completions.create_chat_completions_assistant_message_stream`:
instead of a single outbound ``AssistantMessageStream`` it returns a live
:class:`~otter_ai_core.model_connection.ModelConnection` the caller iterates
inbound server events from and sends outbound client events to.
"""

from __future__ import annotations

from otter_ai_realtime.connection import create_realtime_model_connection
from otter_ai_realtime.hooks import (
    OnConnectEvent,
    OnConnectHook,
    OnSessionUpdateEvent,
    OnSessionUpdateHook,
    RealtimeHooks,
)
from otter_ai_realtime.models import (
    RealtimeApi,
    RealtimeCost,
    RealtimeModel,
    RealtimeSessionConfig,
)
from otter_ai_realtime.options import RealtimeModelOptions

__version__ = "0.1.0"

__all__ = [
    # version
    "__version__",
    # data model
    "RealtimeApi",
    "RealtimeCost",
    "RealtimeModel",
    "RealtimeSessionConfig",
    # hooks
    "RealtimeHooks",
    "OnSessionUpdateEvent",
    "OnSessionUpdateHook",
    "OnConnectEvent",
    "OnConnectHook",
    # options bundle
    "RealtimeModelOptions",
    # seam
    "create_realtime_model_connection",
]

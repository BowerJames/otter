"""Model-connection subpackage facade.

This package is the typed specialisation of
:mod:`otter_ai_core.connection` for live, bidirectional model APIs
(Realtime / Responses-style). It fixes the connection's generic event types
to concrete unions:

* :data:`ModelConnection` — ``Connection[ClientEvent, ServerEvent]``.
* :data:`ModelConnectionFn` — ``ConnectionFn[ClientEvent, ServerEvent]``, the
  options-bound producer
  (:data:`ConnectionFn` is
  ``Callable[[Context, asyncio.Event], Connection[TClient, TEvent]]``).
* :data:`ModelConnectionFnBuilder` — ``Callable[[TOptions], ModelConnectionFn]``,
  the bidirectional peer of
  :data:`otter_ai_core.assistant_message_stream.AssistantMessageStreamFnBuilder`.
* :data:`ClientEvent` / :data:`ServerEvent` — the discriminated unions a
  caller and a backend exchange, plus their member event classes.

It is a supported import surface (Strategy A — two-layer facade): callers may
import from :mod:`otter_ai_core.model_connection`. The public surface is
declared via :data:`__all__`. Core still defines **no transports, providers,
API registry, or dispatch** — only the generic connection runtime (in
:mod:`otter_ai_core.connection`) and these typed aliases / event unions.
"""

from .client_events import (
    AbortResponseEvent,
    ClientEvent,
    ClientEventTypes,
    ContextItemAddEvent,
    ResponseCreate,
)
from .model_connection import (
    ModelConnection,
    ModelConnectionFn,
    ModelConnectionFnBuilder,
)
from .server_events import (
    ConnectionErrorEvent,
    ContextItemAddedEvent,
    ResponseAbortedEvent,
    ResponseDoneEvent,
    ResponseErrorEvent,
    ResponseStartedEvent,
    ResponseStopReasons,
    ResponseTextDoneEvent,
    ResponseTextStartEvent,
    ResponseTextUpdatedEvent,
    ResponseThinkingDoneEvent,
    ResponseThinkingStartEvent,
    ResponseThinkingUpdateEvent,
    ResponseToolCallDoneEvent,
    ResponseToolCallStartEvent,
    ResponseToolCallUpdateEvent,
    ServerEvent,
    ServerEventTypes,
)

__all__ = [
    # typed aliases
    "ModelConnection",
    "ModelConnectionFn",
    "ModelConnectionFnBuilder",
    # client events
    "ClientEvent",
    "ClientEventTypes",
    "ContextItemAddEvent",
    "ResponseCreate",
    "AbortResponseEvent",
    # server events
    "ServerEvent",
    "ServerEventTypes",
    "ResponseStopReasons",
    "ContextItemAddedEvent",
    "ConnectionErrorEvent",
    "ResponseStartedEvent",
    "ResponseTextStartEvent",
    "ResponseTextUpdatedEvent",
    "ResponseTextDoneEvent",
    "ResponseThinkingStartEvent",
    "ResponseThinkingUpdateEvent",
    "ResponseThinkingDoneEvent",
    "ResponseToolCallStartEvent",
    "ResponseToolCallUpdateEvent",
    "ResponseToolCallDoneEvent",
    "ResponseDoneEvent",
    "ResponseErrorEvent",
    "ResponseAbortedEvent",
]

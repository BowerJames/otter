"""Assistant-message-stream subpackage facade.

This package groups the streaming-event protocol and the typed stream aliases
used to build a single assistant message:

* the :data:`AssistantMessageEvent` family (a discriminated union on ``type``)
  — a Python port of the ``AssistantMessageEvent`` protocol from
  ``@earendil-works/pi-ai``; and
* the typed aliases :data:`AssistantMessageStream`, :data:`AssistantMessageWriter`,
  and the producer-side seam type :data:`AssistantMessageStreamFn`, which
  specialize the generic stream runtime in :mod:`otter_ai_core.stream`.

It is a supported import surface (Strategy A — two-layer facade): callers may
import from :mod:`otter_ai_core.assistant_message_stream`. The public surface
is declared via :data:`__all__`.
"""

from .assistant_message_events import (
    AssistantDoneEvent,
    AssistantDoneReason,
    AssistantErrorEvent,
    AssistantMessageEvent,
    AssistantStartEvent,
    AssistantTextDeltaEvent,
    AssistantTextEndEvent,
    AssistantTextStartEvent,
    AssistantThinkingDeltaEvent,
    AssistantThinkingEndEvent,
    AssistantThinkingStartEvent,
    AssistantToolCallDeltaEvent,
    AssistantToolCallEndEvent,
    AssistantToolCallStartEvent,
    EventErrorReason,
)
from .assistant_message_stream import (
    AssistantMessageStream,
    AssistantMessageStreamFn,
    AssistantMessageWriter,
)

__all__ = [
    # typed aliases
    "AssistantMessageStream",
    "AssistantMessageStreamFn",
    "AssistantMessageWriter",
    # events
    "AssistantDoneEvent",
    "AssistantDoneReason",
    "AssistantErrorEvent",
    "AssistantMessageEvent",
    "AssistantStartEvent",
    "AssistantTextDeltaEvent",
    "AssistantTextEndEvent",
    "AssistantTextStartEvent",
    "AssistantThinkingDeltaEvent",
    "AssistantThinkingEndEvent",
    "AssistantThinkingStartEvent",
    "AssistantToolCallDeltaEvent",
    "AssistantToolCallEndEvent",
    "AssistantToolCallStartEvent",
    "EventErrorReason",
]

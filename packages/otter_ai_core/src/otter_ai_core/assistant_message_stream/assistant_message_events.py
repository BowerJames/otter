"""Streaming event model for building assistant messages.

This module models the events emitted while a singular assistant message is being
produced by an LLM provider.

It is **data-only**: no transport, no provider registry, no ``stream()``
dispatch. Only the Pydantic v2 data structures a consumer renders or a producer
pushes. Every field it references is defined by the existing context model.

The protocol is a Python port of the ``AssistantMessageEvent`` protocol from
the upstream ``@earendil-works/pi-ai`` library. It is a single discriminated
union over ``type``.

Producer contract
-----------------
A stream should emit ``start`` before any partial updates, then terminate with
**exactly one** of:

* ``done`` — carrying the final message, with a ``reason`` mirroring
  ``stop_reason`` (``"stop"`` / ``"length"`` / ``"tool_use"``), or
* ``error`` — carrying the final message (with ``stop_reason`` ``"error"``
  or ``"aborted"`` and ``error_message`` set) and ``reason`` of ``"error"``
  or ``"aborted"``. Partial content received before the failure is preserved
  on the message.

Every non-terminal event carries a ``partial`` snapshot of the in-progress
message, so a consumer can render state from the latest event alone. While
the message is in flight that ``partial`` snapshot has
``stop_reason=None``; only the terminal ``done``/``error`` message carries a
non-``None`` stop reason (mirrored in the event's ``reason``).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from otter_ai_core.context import Role
from otter_ai_core.context.content import ToolCall
from otter_ai_core.context.messages import AssistantMessage, StopReason
from otter_ai_core.event import Event

# Reason for the message to terminate with a ``done`` event.
AssistantDoneReason = Literal[StopReason.Stop, StopReason.Length, StopReason.ToolUse]

#: Reason an event stream terminated with an ``error`` event.
EventErrorReason = Literal[StopReason.Error, StopReason.Aborted]


class AssistantMessageEventType(StrEnum):
    """The ``type`` field of an assistant-message streaming event.

    Members preserve the snake_case string values of the original ``Literal``
    annotations, so the JSON wire format (a port of the
    ``AssistantMessageEvent`` protocol from ``@earendil-works/pi-ai``) is
    unchanged. It is the assistant-message-stream peer of
    :class:`~otter_ai_core.model_connection.ServerContextEventType` /
    :class:`~otter_ai_core.model_connection.ClientContextEventType`.
    """

    START = "start"
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"
    THINKING_START = "thinking_start"
    THINKING_DELTA = "thinking_delta"
    THINKING_END = "thinking_end"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL_END = "tool_call_end"
    DONE = "done"
    ERROR = "error"


# --------------------------------------------------------------------------- #
# Assistant events
# --------------------------------------------------------------------------- #
# Port of the ``AssistantMessageEvent`` protocol from @earendil-works/pi-ai.
# Every non-terminal leaf carries ``partial: AssistantMessage`` — a full
# snapshot of the in-progress message — so a consumer can render state from the
# latest event alone if desired.


class AssistantStartEvent(Event[AssistantMessageEventType]):
    """Stream begins. ``partial`` is the empty-start assistant message."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.Assistant]
    type: Literal[AssistantMessageEventType.START] = AssistantMessageEventType.START
    partial: AssistantMessage


class AssistantTextStartEvent(Event[AssistantMessageEventType]):
    """A text content block begins at ``content_index``."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.Assistant]
    type: Literal[AssistantMessageEventType.TEXT_START] = AssistantMessageEventType.TEXT_START
    content_index: int
    partial: AssistantMessage


class AssistantTextDeltaEvent(Event[AssistantMessageEventType]):
    """A chunk of text appended to the block at ``content_index``."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.Assistant]
    type: Literal[AssistantMessageEventType.TEXT_DELTA] = AssistantMessageEventType.TEXT_DELTA
    content_index: int
    delta: str
    partial: AssistantMessage


class AssistantTextEndEvent(Event[AssistantMessageEventType]):
    """The text content block at ``content_index`` is complete."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.Assistant]
    type: Literal[AssistantMessageEventType.TEXT_END] = AssistantMessageEventType.TEXT_END
    content_index: int
    content: str
    partial: AssistantMessage


class AssistantThinkingStartEvent(Event[AssistantMessageEventType]):
    """A thinking/reasoning block begins at ``content_index``."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.Assistant]
    type: Literal[AssistantMessageEventType.THINKING_START] = (
        AssistantMessageEventType.THINKING_START
    )
    content_index: int
    partial: AssistantMessage


class AssistantThinkingDeltaEvent(Event[AssistantMessageEventType]):
    """A chunk of thinking appended to the block at ``content_index``."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.Assistant]
    type: Literal[AssistantMessageEventType.THINKING_DELTA] = (
        AssistantMessageEventType.THINKING_DELTA
    )
    content_index: int
    delta: str
    partial: AssistantMessage


class AssistantThinkingEndEvent(Event[AssistantMessageEventType]):
    """The thinking content block at ``content_index`` is complete."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.Assistant]
    type: Literal[AssistantMessageEventType.THINKING_END] = AssistantMessageEventType.THINKING_END
    content_index: int
    content: str
    partial: AssistantMessage


class AssistantToolCallStartEvent(Event[AssistantMessageEventType]):
    """A tool call begins at ``content_index`` (arguments not yet known)."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.Assistant]
    type: Literal[AssistantMessageEventType.TOOL_CALL_START] = (
        AssistantMessageEventType.TOOL_CALL_START
    )
    content_index: int
    partial: AssistantMessage


class AssistantToolCallDeltaEvent(Event[AssistantMessageEventType]):
    """A chunk of (partial-JSON) tool arguments for the call at ``content_index``.

    During streaming, ``partial.content[content_index].arguments`` holds the
    best-effort parse of the partial JSON and may be incomplete.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.Assistant]
    type: Literal[AssistantMessageEventType.TOOL_CALL_DELTA] = (
        AssistantMessageEventType.TOOL_CALL_DELTA
    )
    content_index: int
    delta: str
    partial: AssistantMessage


class AssistantToolCallEndEvent(Event[AssistantMessageEventType]):
    """The tool call at ``content_index`` is complete with validated arguments."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.Assistant]
    type: Literal[AssistantMessageEventType.TOOL_CALL_END] = AssistantMessageEventType.TOOL_CALL_END
    content_index: int
    tool_call: ToolCall
    partial: AssistantMessage


class AssistantDoneEvent(Event[AssistantMessageEventType]):
    """Stream completed successfully. ``reason`` mirrors ``stop_reason``."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.Assistant]
    type: Literal[AssistantMessageEventType.DONE] = AssistantMessageEventType.DONE
    reason: AssistantDoneReason
    message: AssistantMessage


class AssistantErrorEvent(Event[AssistantMessageEventType]):
    """Stream terminated in error or was aborted.

    ``error`` is the final assistant message (with ``stop_reason`` ``"error"``
    or ``"aborted"`` and ``error_message`` set); any partial content received
    before the failure is preserved on it.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.Assistant]
    type: Literal[AssistantMessageEventType.ERROR] = AssistantMessageEventType.ERROR
    reason: EventErrorReason
    error: AssistantMessage


#: Discriminated union of all assistant streaming events.
AssistantMessageEvent = Annotated[
    AssistantStartEvent
    | AssistantTextStartEvent
    | AssistantTextDeltaEvent
    | AssistantTextEndEvent
    | AssistantThinkingStartEvent
    | AssistantThinkingDeltaEvent
    | AssistantThinkingEndEvent
    | AssistantToolCallStartEvent
    | AssistantToolCallDeltaEvent
    | AssistantToolCallEndEvent
    | AssistantDoneEvent
    | AssistantErrorEvent,
    Field(discriminator="type"),
]

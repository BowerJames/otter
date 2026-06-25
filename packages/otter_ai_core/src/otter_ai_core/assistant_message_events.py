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
* ``error`` — carrying the final message (with ``stop_reason`` ``"error"`` or
  ``"aborted"`` and ``error_message`` set) and ``reason`` of ``"error"`` or
  ``"aborted"``. Partial content received before the failure is preserved on
  the message.

Every non-terminal event carries a ``partial`` snapshot of the in-progress
message, so a consumer can render state from the latest event alone.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from otter_ai_core.content import ToolCall
from otter_ai_core.messages import AssistantMessage

#: ``StopReason`` values that terminate a successful assistant turn.
#: (See :data:`otter_ai_core.types.StopReason`; ``error``/``aborted`` terminate via
#: the :data:`EventErrorReason` type instead.)
AssistantDoneReason = Literal["stop", "length", "tool_use"]

#: Reason an event stream terminated with an ``error`` event.
EventErrorReason = Literal["error", "aborted"]


# --------------------------------------------------------------------------- #
# Assistant events
# --------------------------------------------------------------------------- #
# Port of the ``AssistantMessageEvent`` protocol from @earendil-works/pi-ai.
# Every non-terminal leaf carries ``partial: AssistantMessage`` — a full
# snapshot of the in-progress message — so a consumer can render state from the
# latest event alone if desired.


class AssistantStartEvent(BaseModel):
    """Stream begins. ``partial`` is the empty-start assistant message."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"]
    type: Literal["start"]
    partial: AssistantMessage


class AssistantTextStartEvent(BaseModel):
    """A text content block begins at ``content_index``."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"]
    type: Literal["text_start"]
    content_index: int
    partial: AssistantMessage


class AssistantTextDeltaEvent(BaseModel):
    """A chunk of text appended to the block at ``content_index``."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"]
    type: Literal["text_delta"]
    content_index: int
    delta: str
    partial: AssistantMessage


class AssistantTextEndEvent(BaseModel):
    """The text content block at ``content_index`` is complete."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"]
    type: Literal["text_end"]
    content_index: int
    content: str
    partial: AssistantMessage


class AssistantThinkingStartEvent(BaseModel):
    """A thinking/reasoning block begins at ``content_index``."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"]
    type: Literal["thinking_start"]
    content_index: int
    partial: AssistantMessage


class AssistantThinkingDeltaEvent(BaseModel):
    """A chunk of thinking appended to the block at ``content_index``."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"]
    type: Literal["thinking_delta"]
    content_index: int
    delta: str
    partial: AssistantMessage


class AssistantThinkingEndEvent(BaseModel):
    """The thinking content block at ``content_index`` is complete."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"]
    type: Literal["thinking_end"]
    content_index: int
    content: str
    partial: AssistantMessage


class AssistantToolCallStartEvent(BaseModel):
    """A tool call begins at ``content_index`` (arguments not yet known)."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"]
    type: Literal["tool_call_start"]
    content_index: int
    partial: AssistantMessage


class AssistantToolCallDeltaEvent(BaseModel):
    """A chunk of (partial-JSON) tool arguments for the call at ``content_index``.

    During streaming, ``partial.content[content_index].arguments`` holds the
    best-effort parse of the partial JSON and may be incomplete.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"]
    type: Literal["tool_call_delta"]
    content_index: int
    delta: str
    partial: AssistantMessage


class AssistantToolCallEndEvent(BaseModel):
    """The tool call at ``content_index`` is complete with validated arguments."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"]
    type: Literal["tool_call_end"]
    content_index: int
    tool_call: ToolCall
    partial: AssistantMessage


class AssistantDoneEvent(BaseModel):
    """Stream completed successfully. ``reason`` mirrors ``stop_reason``."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"]
    type: Literal["done"]
    reason: AssistantDoneReason
    message: AssistantMessage


class AssistantErrorEvent(BaseModel):
    """Stream terminated in error or was aborted.

    ``error`` is the final assistant message (with ``stop_reason`` ``"error"``
    or ``"aborted"`` and ``error_message`` set); any partial content received
    before the failure is preserved on it.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"]
    type: Literal["error"]
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

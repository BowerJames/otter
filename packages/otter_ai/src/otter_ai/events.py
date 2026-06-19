"""Streaming event model for building context items.

This module models the events emitted while a context item (an
:class:`~otter_ai.messages.AssistantMessage`, a
:class:`~otter_ai.messages.UserMessage`, or a
:class:`~otter_ai.messages.ToolResultMessage`) is being produced — for example
by an LLM provider (assistant content), a realtime transcription API (user
content), or a tool executor (tool results).

It is **data-only**: no transport, no provider registry, no ``stream()``
dispatch. Only the Pydantic v2 data structures a consumer renders or a producer
pushes. Every field it references is defined by the existing context model.

The protocol mirrors the assistant event protocol of the upstream
``@earendil-works/pi-ai`` library, and extends it with user and tool-result
families. Each family is a discriminated union over ``type``, and all three are
combined into :data:`ContextItemEvent`.

Producer contract
-----------------
For each family a stream should emit ``start`` before any partial updates, then
terminate with **exactly one** of:

* ``done`` — carrying the final message (assistant ``done`` also carries a
  ``reason`` mirroring ``stop_reason``; user/tool-result ``done`` carry only
  the message), or
* ``error`` — carrying the final message (with its role-appropriate
  ``error``/aborted marker) and ``reason`` of ``"error"`` or ``"aborted"``.
  Partial content received before the failure is preserved on the message.

Two conventions are documented (not schema-enforced):

* **Partials use the list form.** ``UserMessage.content`` is ``str |
  list[UserContent]``; when streaming, producers build the ``list`` form so the
  ``content_index`` of every ``*_delta``/``*_end`` event is well-defined.
* **Aborted tool results are marked.** An aborted tool-result partial carries
  ``is_error=True`` so it can be fed back to the model as an error (the model
  cannot act on a half-finished result).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from otter_ai.content import ToolCall
from otter_ai.messages import AssistantMessage, ToolResultMessage, UserMessage

#: ``StopReason`` values that terminate a successful assistant turn.
#: (See :data:`otter_ai.types.StopReason`; ``error``/``aborted`` terminate via
#: the :data:`EventErrorReason` family instead.)
AssistantDoneReason = Literal["stop", "length", "tool_use"]

#: Reason an event stream terminated with an ``error`` event. Shared by all
#: three families.
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


# --------------------------------------------------------------------------- #
# User events
# --------------------------------------------------------------------------- #
# New in otter; motivated by realtime transcription APIs (e.g. OpenAI
# Realtime) that stream user-message content as deltas.


class UserStartEvent(BaseModel):
    """Stream begins. ``partial`` is the empty-start user message."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user"]
    type: Literal["start"]
    partial: UserMessage


class UserTextStartEvent(BaseModel):
    """A text content block begins at ``content_index``."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user"]
    type: Literal["text_start"]
    content_index: int
    partial: UserMessage


class UserTextDeltaEvent(BaseModel):
    """A chunk of text appended to the block at ``content_index``."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user"]
    type: Literal["text_delta"]
    content_index: int
    delta: str
    partial: UserMessage


class UserTextEndEvent(BaseModel):
    """The text content block at ``content_index`` is complete."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user"]
    type: Literal["text_end"]
    content_index: int
    content: str
    partial: UserMessage


class UserDoneEvent(BaseModel):
    """Stream completed. Carries the final user message (no ``reason``)."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user"]
    type: Literal["done"]
    message: UserMessage


class UserErrorEvent(BaseModel):
    """Stream terminated in error or was aborted.

    ``error`` is the final user message; any partial content received before
    the failure is preserved on it.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["user"]
    type: Literal["error"]
    reason: EventErrorReason
    error: UserMessage


#: Discriminated union of all user streaming events.
UserMessageEvent = Annotated[
    UserStartEvent
    | UserTextStartEvent
    | UserTextDeltaEvent
    | UserTextEndEvent
    | UserDoneEvent
    | UserErrorEvent,
    Field(discriminator="type"),
]

#: Plain union of assistant and user message events (excludes tool results).
#
# Not a discriminated union: the two families share ``type`` values
# (``start``/``text_*``/``done``/``error``) and are distinguished by ``role``.
# It routes deterministically because every leaf carries strict ``role``/
# ``type`` Literals together with ``extra="forbid"``. (Same rationale as
# :data:`ContextItemEvent`.)
MessageEvent = AssistantMessageEvent | UserMessageEvent


# --------------------------------------------------------------------------- #
# Tool-result events
# --------------------------------------------------------------------------- #
# New in otter; models streamed/abortable tool execution results.


class ToolResultStartEvent(BaseModel):
    """Stream begins. ``partial`` is the empty-start tool result."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["tool_result"]
    type: Literal["start"]
    partial: ToolResultMessage


class ToolResultTextStartEvent(BaseModel):
    """A text content block begins at ``content_index`` (e.g. streamed stdout)."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["tool_result"]
    type: Literal["text_start"]
    content_index: int
    partial: ToolResultMessage


class ToolResultTextDeltaEvent(BaseModel):
    """A chunk of text appended to the block at ``content_index``."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["tool_result"]
    type: Literal["text_delta"]
    content_index: int
    delta: str
    partial: ToolResultMessage


class ToolResultTextEndEvent(BaseModel):
    """The text content block at ``content_index`` is complete."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["tool_result"]
    type: Literal["text_end"]
    content_index: int
    content: str
    partial: ToolResultMessage


class ToolResultDoneEvent(BaseModel):
    """Stream completed. Carries the final tool result (no ``reason``).

    ``done`` covers both successful results and ``is_error=True`` tool errors
    (the tool ran and returned an error) — both are normal completions.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["tool_result"]
    type: Literal["done"]
    message: ToolResultMessage


class ToolResultErrorEvent(BaseModel):
    """Stream terminated in error or was aborted.

    ``error`` is the final tool result; any partial content received before the
    failure is preserved on it. By convention an aborted partial carries
    ``is_error=True`` so it can be fed back to the model as an error.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["tool_result"]
    type: Literal["error"]
    reason: EventErrorReason
    error: ToolResultMessage


#: Discriminated union of all tool-result streaming events.
ToolResultMessageEvent = Annotated[
    ToolResultStartEvent
    | ToolResultTextStartEvent
    | ToolResultTextDeltaEvent
    | ToolResultTextEndEvent
    | ToolResultDoneEvent
    | ToolResultErrorEvent,
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------- #
# Combined union
# --------------------------------------------------------------------------- #
#
# ``ContextItemEvent`` is a *plain union* of the three per-role discriminated
# unions, not itself a discriminated union. Pydantic v2 requires each member of
# a discriminated union to map to a unique discriminator value, but all twelve
# assistant leaves share ``role="assistant"`` — so a discriminator of ``role``
# is rejected, and a callable composite (``role``+``type``) discriminator is
# only supported for ``TypedDict``, not ``BaseModel``. The plain-union form
# routes deterministically because every leaf carries strict ``role``/``type``
# Literals together with ``extra="forbid"``.
ContextItemEvent = AssistantMessageEvent | UserMessageEvent | ToolResultMessageEvent

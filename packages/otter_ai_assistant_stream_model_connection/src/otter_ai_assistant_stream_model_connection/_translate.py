"""Stateless translation: ``AssistantMessageEvent`` → ``ServerEvent``.

This module is the single place that maps the
:mod:`otter_ai_core.assistant_message_stream` event protocol onto the
:mod:`otter_ai_core.model_connection` server-event protocol. The two protocols
mirror each other almost 1:1, and every source event already carries a
complete ``partial: AssistantMessage`` snapshot (the producer accumulates it),
so the translation is **stateless** — unlike
:mod:`otter_ai_realtime._events`, which must build the partial from wire
frames.

Mapping
-------
Each non-terminal assistant event maps to exactly one server event, passing
``partial`` through verbatim (provenance ``api``/``provider``/``model``/
``usage``/… is inert and untouched). The ``delta``/``content`` fields the
source carries have no counterpart in the target protocol (which snapshots only
``partial``), so they are dropped.

* ``AssistantStartEvent``                → ``ResponseStartedEvent``
* ``AssistantText*Event`` (start/delta)  → ``ResponseText*Event``
* ``AssistantTextEndEvent``              → ``ResponseTextDoneEvent``
* ``AssistantThinking*Event``            → ``ResponseThinking*Event``
* ``AssistantToolCall*Event``            → ``ResponseToolCall*Event``
* ``AssistantDoneEvent``                 → ``ResponseDoneEvent`` **+**
  auto-append + ``ContextItemAddedEvent``
* ``AssistantErrorEvent`` (``"aborted"``) → ``ResponseAbortedEvent``
* ``AssistantErrorEvent`` (``"error"``)   → ``ResponseErrorEvent``

Context side-effects
--------------------
Only a clean ``AssistantDoneEvent`` mutates the caller's
:class:`~otter_ai_core.Context`: the final :class:`~AssistantMessage` is
appended as an :class:`AssistantContextItem` (with a freshly-generated
``uuid4`` ``item_id``) and announced via a ``ContextItemAddedEvent`` —
mirroring how a Realtime server commits a completed response as a
``conversation.item.created`` frame. Errored/aborted responses are **not**
appended: they are unreplayable (see :mod:`otter_ai_core.normalize`).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from otter_ai_core import AssistantContextItem
from otter_ai_core.assistant_message_stream import (
    AssistantDoneEvent,
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
)
from otter_ai_core.context import ContentType, Role, StopReason
from otter_ai_core.model_connection import (
    ContextItemAddedEvent,
    ResponseAbortedEvent,
    ResponseDoneEvent,
    ResponseErrorEvent,
    ResponseStartedEvent,
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
)

if TYPE_CHECKING:
    from otter_ai_core import Context


def translate(event: AssistantMessageEvent, context: Context) -> list[ServerEvent]:
    """Map one assistant streaming event to zero or more server events.

    Returns a list because a clean ``AssistantDoneEvent`` yields two events
    (the ``ResponseDoneEvent`` plus the auto-append ``ContextItemAddedEvent``);
    every other event yields exactly one. ``context`` is mutated only on a
    clean done.
    """
    if isinstance(event, AssistantStartEvent):
        return [
            ResponseStartedEvent(
                type="response.started",
                role=Role.Assistant,
                partial=event.partial,
            )
        ]
    if isinstance(event, AssistantTextStartEvent):
        return [
            ResponseTextStartEvent(
                type="response.text_content.started",
                role=Role.Assistant,
                content_type=ContentType.Text,
                content_index=event.content_index,
                partial=event.partial,
            )
        ]
    if isinstance(event, AssistantTextDeltaEvent):
        return [
            ResponseTextUpdatedEvent(
                type="response.text_content.updated",
                role=Role.Assistant,
                content_type=ContentType.Text,
                content_index=event.content_index,
                partial=event.partial,
            )
        ]
    if isinstance(event, AssistantTextEndEvent):
        return [
            ResponseTextDoneEvent(
                type="response.text_content.done",
                role=Role.Assistant,
                content_type=ContentType.Text,
                content_index=event.content_index,
                partial=event.partial,
            )
        ]
    if isinstance(event, AssistantThinkingStartEvent):
        return [
            ResponseThinkingStartEvent(
                type="response.thinking_content.started",
                role=Role.Assistant,
                content_type=ContentType.Thinking,
                content_index=event.content_index,
                partial=event.partial,
            )
        ]
    if isinstance(event, AssistantThinkingDeltaEvent):
        return [
            ResponseThinkingUpdateEvent(
                type="response.thinking_content.updated",
                role=Role.Assistant,
                content_type=ContentType.Thinking,
                content_index=event.content_index,
                partial=event.partial,
            )
        ]
    if isinstance(event, AssistantThinkingEndEvent):
        return [
            ResponseThinkingDoneEvent(
                type="response.thinking_content.done",
                role=Role.Assistant,
                content_type=ContentType.Thinking,
                content_index=event.content_index,
                partial=event.partial,
            )
        ]
    if isinstance(event, AssistantToolCallStartEvent):
        return [
            ResponseToolCallStartEvent(
                type="response.tool_call.started",
                role=Role.Assistant,
                content_type=ContentType.ToolCall,
                content_index=event.content_index,
                partial=event.partial,
            )
        ]
    if isinstance(event, AssistantToolCallDeltaEvent):
        return [
            ResponseToolCallUpdateEvent(
                type="response.tool_call.updated",
                role=Role.Assistant,
                content_type=ContentType.ToolCall,
                content_index=event.content_index,
                partial=event.partial,
            )
        ]
    if isinstance(event, AssistantToolCallEndEvent):
        return [
            ResponseToolCallDoneEvent(
                type="response.tool_call.done",
                role=Role.Assistant,
                content_type=ContentType.ToolCall,
                content_index=event.content_index,
                partial=event.partial,
            )
        ]
    if isinstance(event, AssistantDoneEvent):
        return _done(event, context)
    if isinstance(event, AssistantErrorEvent):
        return [_error(event)]
    # Unknown event variant — the producer protocol shouldn't emit any other
    # type, but a forward-compatible producer is tolerated (dropped silently).
    return []


# --------------------------------------------------------------------------- #
# Terminal events
# --------------------------------------------------------------------------- #


def _done(event: AssistantDoneEvent, context: Context) -> list[ServerEvent]:
    """Emit ``ResponseDoneEvent`` then commit the message to the context.

    The final :class:`AssistantMessage` is appended as an
    :class:`AssistantContextItem` with a server-generated ``uuid4`` id, and a
    matching ``ContextItemAddedEvent`` is emitted — the local equivalent of a
    Realtime server's ``conversation.item.created`` after ``response.done``.
    """
    done = ResponseDoneEvent(
        type="response.done",
        role=Role.Assistant,
        reason=event.reason,
        partial=event.message,
    )
    item = AssistantContextItem.from_message(event.message, str(uuid.uuid4()))
    context.items.append(item)
    added = ContextItemAddedEvent(
        type="context_item.added",
        item_id=item.id,
        role=Role.Assistant,
        item=item,
    )
    return [done, added]


def _error(event: AssistantErrorEvent) -> ServerEvent:
    """Route an errored/aborted stream onto the matching server terminal.

    ``reason`` literal-matches the target event's ``Literal[StopReason]``
    exactly (precedent: :mod:`otter_ai_realtime._events`). Errored/aborted
    responses are **not** appended to the context (unreplayable).
    """
    partial = event.error
    if event.reason == StopReason.Aborted:
        return ResponseAbortedEvent(
            type="response.aborted",
            role=Role.Assistant,
            reason=StopReason.Aborted,
            partial=partial,
        )
    return ResponseErrorEvent(
        type="response.error",
        role=Role.Assistant,
        reason=StopReason.Error,
        partial=partial,
    )


__all__ = ["translate"]

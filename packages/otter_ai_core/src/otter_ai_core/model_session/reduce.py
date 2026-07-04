"""Pure translation from raw :data:`~otter_ai_core.model_connection.ServerEvent`
to reduced :data:`~otter_ai_core.model_session.events.SessionEvent`.

This module is the **single place** that knows about both event families. The
bus is transport-agnostic (it dispatches :data:`SessionEvent` only); the inbound
pump owns phase/context mutation; :func:`reduce_server_event` owns only the
vocabulary rewrite — wire shape to app shape. It is a pure, stateless function
with no asyncio, bus, or session dependency, so it is trivially unit-testable
with fixture events and no live connection.

Reduction rules
---------------
* **Streaming collapse.** The nine ``response.*_content.*`` /
  ``response.tool_call.*`` variants (Started/Updated/Done across
  text/thinking/toolcall) all carry the full accumulated ``partial``
  :class:`~otter_ai_core.AssistantMessage` snapshot, so they collapse to a
  single :class:`~otter_ai_core.model_session.events.ResponseDeltaEvent` with
  no loss of consumer-actionable information.
* **Terminal payload rename.** Raw terminals carry ``partial`` (the snapshot at
  the end); bus terminals carry ``message`` (the snapshot semantically
  promoted to "the response's message"). The reduction performs that rename.
* **1:1 elsewhere.** ``ResponseStarted``, ``ContextItemAdded``,
  ``ConnectionError`` map directly to their bus counterparts.

What the reduction does NOT do
------------------------------
It is **stateless** and assumes a well-formed protocol. It does not:

* mutate phase (the inbound pump does, on terminal events) — reduction has no
  awareness of the session's phase machine;
* mutate the live :class:`~otter_ai_core.Context` (the inbound pump does, on
  ``ContextItemAdded``);
* synthesize missing events (e.g. a missing ``ResponseStarted``) — if a
  provider misbehaves, detecting/repairing that is a session-level concern,
  not a translator's. Promoting to a stateful validator is a separate
  component, not an evolution of this function.

The function returns an :class:`~collections.abc.Iterator` (rather than a
single value) so that future 0-case (filter) and N-case (synthesize) mappings
need no signature change; today every case yields exactly one event.

Name overlap
------------
Several raw classes share names with their bus counterparts
(``ResponseStartedEvent``, ``ResponseDoneEvent``, …). Where they collide, the
raw class is imported here under a ``Raw`` alias to keep the two layers
visually distinct in the only file that bridges them.
"""

from __future__ import annotations

from collections.abc import Iterator

from otter_ai_core.context import Role
from otter_ai_core.model_connection import server_events as raw
from otter_ai_core.model_connection.server_events import ServerEvent

from .events import (
    ContextItemAddedEvent,
    ResponseAbortedEvent,
    ResponseDeltaEvent,
    ResponseDoneEvent,
    ResponseErrorEvent,
    ResponseStartedEvent,
    SessionErrorEvent,
    SessionEvent,
    SessionEventTypes,
)


def reduce_server_event(event: ServerEvent) -> Iterator[SessionEvent]:
    """Translate one raw server event into zero or more bus events.

    Pure and stateless. See module docstring for the reduction rules.
    """
    match event:
        case raw.ResponseStartedEvent(partial=partial):
            yield ResponseStartedEvent(
                type=SessionEventTypes.ResponseStarted,
                role=Role.Assistant,
                partial=partial,
            )

        case (
            raw.ResponseTextStartEvent(partial=partial)
            | raw.ResponseTextUpdatedEvent(partial=partial)
            | raw.ResponseTextDoneEvent(partial=partial)
            | raw.ResponseThinkingStartEvent(partial=partial)
            | raw.ResponseThinkingUpdateEvent(partial=partial)
            | raw.ResponseThinkingDoneEvent(partial=partial)
            | raw.ResponseToolCallStartEvent(partial=partial)
            | raw.ResponseToolCallUpdateEvent(partial=partial)
            | raw.ResponseToolCallDoneEvent(partial=partial)
        ):
            yield ResponseDeltaEvent(
                type=SessionEventTypes.ResponseDelta,
                role=Role.Assistant,
                partial=partial,
            )

        case raw.ResponseDoneEvent(partial=partial):
            yield ResponseDoneEvent(
                type=SessionEventTypes.ResponseDone,
                role=Role.Assistant,
                message=partial,
            )

        case raw.ResponseErrorEvent(partial=partial):
            yield ResponseErrorEvent(
                type=SessionEventTypes.ResponseError,
                role=Role.Assistant,
                message=partial,
            )

        case raw.ResponseAbortedEvent(partial=partial):
            yield ResponseAbortedEvent(
                type=SessionEventTypes.ResponseAborted,
                role=Role.Assistant,
                message=partial,
            )

        case raw.ConnectionErrorEvent(message=message, reason=reason):
            yield SessionErrorEvent(
                type=SessionEventTypes.SessionError,
                message=message,
                reason=reason,
            )

        case raw.ContextItemAddedEvent(item_id=item_id, role=role, item=item):
            yield ContextItemAddedEvent(
                type=SessionEventTypes.ContextItemAdded,
                item_id=item_id,
                role=role,
                item=item,
            )


__all__ = ["reduce_server_event"]

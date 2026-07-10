"""Reduced, app-facing event family for the model session bus.

The :data:`SessionEvent` family is what
:class:`~otter_ai_core.model_session.ModelSession` publishes to subscribers.
It is a **curated reduction** of the raw
:data:`~otter_ai_core.model_connection.ServerEvent` protocol (15 wire variants
collapsed to 8 bus events), exposing only what consumers care about and
hiding wire-level detail (which content block, which content type, which
content index).

Why a separate family
---------------------
Every streaming :class:`~otter_ai_core.model_connection.ServerEvent` already
carries ``partial``: the *full accumulated* :class:`~otter_ai_core.AssistantMessage`
snapshot, not a delta. So the consumer never does delta math — it replaces its
current message with the snapshot. That means the nine
``response.*_content.*`` / ``response.tool_call.*`` variants (Started/Updated/Done
across text/thinking/toolcall) all carry the same useful payload and can be
collapsed into a single :class:`ResponseDelta` without losing information the
consumer could act on.

Terminology: *response*, not *turn*
-----------------------------------
A *response* is one model generation, start to terminal. A *turn* (in the
agent-loop vocabulary) is a response **plus** its tool execution and results.
This layer does not execute tools and does not know tools exist — it only
observes model responses — so it speaks in responses. The richer *turn*
vocabulary belongs to the agent layer above, which wraps response events with
tool-execution semantics.

Field naming
------------
Streaming events (:class:`ResponseStarted`, :class:`ResponseDelta`) carry
``partial`` — the in-progress, possibly-empty snapshot. Terminal events
(:class:`ResponseDone`, :class:`ResponseError`, :class:`ResponseAborted`)
carry ``message`` — the snapshot at the end of the response (complete for
``Done``, best-effort/interrupted for ``Error``/``Aborted``).

Like the raw protocol family these are Pydantic v2 models with
``extra="forbid"``; unlike the bidirectional-stream runtime itself they are
plain data and remain serializable.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from otter_ai_core.context import AssistantMessage, ContextItem, Role


class SessionEventTypes(StrEnum):
    """Discriminator values for :data:`SessionEvent` variants."""

    ResponseStarted = "response.started"
    ResponseDelta = "response.delta"
    ResponseDone = "response.done"
    ResponseError = "response.error"
    ResponseAborted = "response.aborted"
    ContextItemAdded = "context_item.added"
    SessionError = "session.error"
    SessionClosed = "session.closed"
    HandlerError = "handler.error"


class ResponseStartedEvent(BaseModel):
    """A model response has begun generating.

    ``partial`` carries the initial :class:`AssistantMessage`, typically empty,
    that subsequent :class:`ResponseDeltaEvent` snapshots will populate.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[SessionEventTypes.ResponseStarted]
    role: Literal[Role.Assistant]
    partial: AssistantMessage


class ResponseDeltaEvent(BaseModel):
    """The in-progress response has been updated.

    Emitted for every streaming content event (text/thinking/toolcall
    Started/Updated/Done). ``partial`` carries the full accumulated
    :class:`AssistantMessage` snapshot — the consumer replaces its current
    message with this; there is no delta to apply.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[SessionEventTypes.ResponseDelta]
    role: Literal[Role.Assistant]
    partial: AssistantMessage


class ResponseDoneEvent(BaseModel):
    """The model response finished successfully.

    ``message`` carries the final, fully-assembled :class:`AssistantMessage`.
    Consumers inspect ``message.content`` for :class:`ToolCall` blocks to
    decide whether to execute tools (this layer does not).
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[SessionEventTypes.ResponseDone]
    role: Literal[Role.Assistant]
    message: AssistantMessage


class ResponseErrorEvent(BaseModel):
    """The model response failed.

    ``message`` carries the best-effort :class:`AssistantMessage` at the point
    of failure, which may be empty or partial.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[SessionEventTypes.ResponseError]
    role: Literal[Role.Assistant]
    message: AssistantMessage


class ResponseAbortedEvent(BaseModel):
    """The model response was aborted before completion (e.g. by barge-in).

    ``message`` carries the best-effort :class:`AssistantMessage` at the point
    of abort, which may be empty or partial.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[SessionEventTypes.ResponseAborted]
    role: Literal[Role.Assistant]
    message: AssistantMessage


class ContextItemAddedEvent(BaseModel):
    """A context item has been accepted into the conversation.

    This is the bus echo of a successful
    :meth:`~otter_ai_core.model_session.ModelSession.add_context_item` — the
    backend has accepted the item (an inbound
    :class:`~otter_ai_core.model_connection.ContextItemAddedEvent` arrived).
    The session's live :class:`~otter_ai_core.Context` is mutated only on this
    signal, never on the outbound command.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[SessionEventTypes.ContextItemAdded]
    item_id: str
    role: Role
    item: ContextItem


class SessionErrorEvent(BaseModel):
    """A session-level (transport) failure outside any single response.

    Reduced from :class:`~otter_ai_core.model_connection.ConnectionErrorEvent`
    (WebSocket connect/handshake failure, mid-session transport error). Unlike
    :class:`ResponseErrorEvent` (the outcome of one response), this fires when
    the connection itself fails.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[SessionEventTypes.SessionError]
    message: str
    reason: str


class SessionClosedEvent(BaseModel):
    """The session has ended — the inbound stream is exhausted.

    Emitted once at the end of the inbound pump's ``finally`` block, after
    every other event. Subscribers' iteration over the bus terminates after
    this event (the session also pushes the ``None`` sentinel to drain the
    queue).
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[SessionEventTypes.SessionClosed]


class HandlerErrorEvent(BaseModel):
    """A bus subscriber's handler raised while handling an event.

    This is a **bus-level observability** event, distinct from
    :class:`ResponseErrorEvent` (a model-response failure) and
    :class:`SessionErrorEvent` (a transport-level failure). It is emitted by
    the bus when a registered handler raises; the exception is contained so
    one bad handler cannot kill the bus for the rest.

    Error events do not emit error events: a handler that raises while
    handling a :class:`HandlerErrorEvent` has its failure swallowed silently,
    capping recursion at one level (otherwise a buggy error-handler would feed
    the queue forever).
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[SessionEventTypes.HandlerError]
    #: Discriminator of the event being dispatched when the handler raised.
    event_type: SessionEventTypes
    #: Best-effort name of the offending handler (its ``__name__`` or repr).
    handler_name: str
    #: ``"{ExcTypeName}: {message}"`` of the captured exception.
    error: str


SessionEvent = (
    ResponseStartedEvent
    | ResponseDeltaEvent
    | ResponseDoneEvent
    | ResponseErrorEvent
    | ResponseAbortedEvent
    | ContextItemAddedEvent
    | SessionErrorEvent
    | SessionClosedEvent
    | HandlerErrorEvent
)
"""Discriminated union of all events published on the model session bus."""

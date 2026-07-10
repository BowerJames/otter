"""ModelSession: pump/reduce wiring, SessionClosedEvent, HandlerErrorEvent + cap.

These tests exercise the assembled :class:`ModelSession` against a
:func:`~otter_ai_core.create_bidirectional_channel` pair whose backend the test drives
directly. They cover the three integration behaviors the code review flagged
as untested:

* raw ``ServerEvent``\\ s are reduced and fanned out as ``SessionEvent``\\ s
  via the bus;
* ``SessionClosedEvent`` is emitted once on stream end (before the ``None``
  sentinel that ends the bus's internal queue); and
* a handler that raises has its exception contained and re-emitted as a
  ``HandlerErrorEvent``, and a ``HandlerErrorEvent`` handler that also raises
  is swallowed (recursion cap), so the bus keeps serving events.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from otter_ai_core import (
    AssistantMessage,
    BidirectionalChannel,
    BidirectionalChannelBackend,
    BidirectionalChannelWiring,
    StopReason,
    Usage,
    UsageCost,
    create_bidirectional_channel,
)
from otter_ai_core.context import Role
from otter_ai_core.model_connection.client_events import ClientEvent
from otter_ai_core.model_connection.server_events import (
    ConnectionErrorEvent,
    ResponseDoneEvent,
    ResponseStartedEvent,
    ResponseTextUpdatedEvent,
    ServerEvent,
    ServerEventTypes,
)
from otter_ai_core.model_session.events import (
    HandlerErrorEvent,
    ResponseDeltaEvent,
    SessionClosedEvent,
    SessionEvent,
    SessionEventTypes,
)
from otter_ai_core.model_session.events import (
    ResponseStartedEvent as BusResponseStartedEvent,
)
from otter_ai_core.model_session.model_session import ModelSession


def _usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
        cost=UsageCost(
            input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0
        ),
    )


def _assistant_message() -> AssistantMessage:
    return AssistantMessage(
        role=Role.Assistant,
        content=[],
        api="chat-completions",
        provider="openai",
        model="gpt-4o",
        usage=_usage(),
        stop_reason=StopReason.Stop,
        timestamp=0,
    )


def _collect(
    bucket: list[SessionEvent],
) -> Callable[[SessionEvent], Awaitable[None]]:
    """Build an async handler that appends each received event to ``bucket``."""

    async def handler(event: SessionEvent) -> None:
        bucket.append(event)

    return handler


def _new() -> tuple[
    BidirectionalChannel[ClientEvent, ServerEvent],
    BidirectionalChannelBackend[ClientEvent, ServerEvent],
]:
    """A bare ``create_bidirectional_channel()`` pair (PEP 695 generics aren't
    subscriptable at runtime), mirroring ``test_bidirectional_channel.py``'s
    pattern."""
    wiring: BidirectionalChannelWiring[ClientEvent, ServerEvent]
    wiring = create_bidirectional_channel()
    return wiring.caller, wiring.backend


async def test_raw_server_events_reduced_and_fanned_out() -> None:
    """A raw ``ResponseStarted`` + text update + ``ResponseDone`` reduce to
    ``ResponseStarted`` + ``ResponseDelta`` + ``ResponseDone`` on the bus."""
    conn, backend = _new()
    session = ModelSession(conn)

    started: list[SessionEvent] = []
    deltas: list[SessionEvent] = []
    done: list[SessionEvent] = []
    session.on(SessionEventTypes.ResponseStarted, _collect(started))
    session.on(SessionEventTypes.ResponseDelta, _collect(deltas))
    session.on(SessionEventTypes.ResponseDone, _collect(done))

    msg = _assistant_message()
    backend.push(
        ResponseStartedEvent(
            type=ServerEventTypes.ResponseStarted,
            role=Role.Assistant,
            partial=msg,
        )
    )
    backend.push(
        ResponseTextUpdatedEvent(
            type=ServerEventTypes.ResponseTextContentUpdated,
            role=Role.Assistant,
            content_type="text",
            content_index=0,
            partial=msg,
        )
    )
    backend.push(
        ResponseDoneEvent(
            type=ServerEventTypes.ResponseDone,
            role=Role.Assistant,
            reason="stop",
            partial=msg,
        )
    )
    backend.end()
    await asyncio.sleep(0.05)

    assert len(started) == 1
    assert isinstance(started[0], BusResponseStartedEvent)
    assert len(deltas) == 1
    assert isinstance(deltas[0], ResponseDeltaEvent)
    assert deltas[0].type is SessionEventTypes.ResponseDelta
    assert len(done) == 1
    assert done[0].type is SessionEventTypes.ResponseDone


async def test_terminal_event_resets_phase_to_idle() -> None:
    """``ResponseDone`` on the inbound stream clears the WORKING phase."""
    conn, backend = _new()
    session = ModelSession(conn)

    session._state_machine.set_working()
    backend.push(
        ResponseDoneEvent(
            type=ServerEventTypes.ResponseDone,
            role=Role.Assistant,
            reason="stop",
            partial=_assistant_message(),
        )
    )
    backend.end()
    await asyncio.sleep(0.02)

    assert session._state_machine.phase.value == "idle"


async def test_session_closed_emitted_on_stream_end() -> None:
    """When the inbound stream ends, exactly one ``SessionClosedEvent`` fires."""
    conn, backend = _new()
    session = ModelSession(conn)

    closed: list[SessionEvent] = []
    session.on(SessionEventTypes.SessionClosed, _collect(closed))

    backend.end()
    await asyncio.sleep(0.02)

    assert len(closed) == 1
    assert isinstance(closed[0], SessionClosedEvent)
    assert closed[0].type is SessionEventTypes.SessionClosed


async def test_connection_error_reduced_to_session_error() -> None:
    """A transport-level ``ConnectionError`` reduces to ``SessionError``."""
    conn, backend = _new()
    session = ModelSession(conn)

    errors: list[SessionEvent] = []
    session.on(SessionEventTypes.SessionError, _collect(errors))

    backend.push(
        ConnectionErrorEvent(
            type=ServerEventTypes.ConnectionError,
            message="websocket closed",
            reason="transport_error",
        )
    )
    backend.end()
    await asyncio.sleep(0.02)

    assert len(errors) == 1
    assert errors[0].type is SessionEventTypes.SessionError


async def test_handler_error_emitted_when_handler_raises() -> None:
    """A handler that raises has its failure contained as a HandlerErrorEvent."""
    conn, backend = _new()
    session = ModelSession(conn)

    async def buggy(_e: SessionEvent) -> None:
        raise RuntimeError("boom")

    captured: list[SessionEvent] = []
    session.on(SessionEventTypes.HandlerError, _collect(captured))
    session.on(SessionEventTypes.ResponseDone, buggy)

    backend.push(
        ResponseDoneEvent(
            type=ServerEventTypes.ResponseDone,
            role=Role.Assistant,
            reason="stop",
            partial=_assistant_message(),
        )
    )
    backend.end()
    await asyncio.sleep(0.05)

    assert len(captured) == 1
    assert isinstance(captured[0], HandlerErrorEvent)
    assert captured[0].type is SessionEventTypes.HandlerError
    assert captured[0].event_type is SessionEventTypes.ResponseDone
    assert "boom" in captured[0].error
    assert captured[0].handler_name == "buggy"


async def test_handler_error_recursion_is_capped() -> None:
    """A HandlerError handler that also raises is swallowed — no infinite loop."""
    conn, backend = _new()
    session = ModelSession(conn)

    async def buggy_response(_e: SessionEvent) -> None:
        raise RuntimeError("first boom")

    async def buggy_error(_e: SessionEvent) -> None:
        raise ValueError("nested boom")

    error_events: list[SessionEvent] = []
    session.on(SessionEventTypes.ResponseDone, buggy_response)
    session.on(SessionEventTypes.HandlerError, buggy_error)
    session.on(SessionEventTypes.HandlerError, _collect(error_events))

    backend.push(
        ResponseDoneEvent(
            type=ServerEventTypes.ResponseDone,
            role=Role.Assistant,
            reason="stop",
            partial=_assistant_message(),
        )
    )
    backend.end()
    await asyncio.sleep(0.05)

    # Exactly one HandlerErrorEvent: from buggy_response. buggy_error's failure
    # produced none (swallowed by the isinstance recursion cap).
    assert len(error_events) == 1
    assert isinstance(error_events[0], HandlerErrorEvent)
    assert error_events[0].event_type is SessionEventTypes.ResponseDone
    assert "first boom" in error_events[0].error


async def test_bus_stays_alive_after_handler_error() -> None:
    """After a handler fails and is contained, subsequent events still dispatch."""
    conn, backend = _new()
    session = ModelSession(conn)

    async def buggy(_e: SessionEvent) -> None:
        raise RuntimeError("boom")

    delivered: list[SessionEvent] = []
    session.on(SessionEventTypes.ResponseDone, buggy)
    session.on(SessionEventTypes.ResponseDelta, _collect(delivered))

    msg = _assistant_message()
    backend.push(
        ResponseDoneEvent(
            type=ServerEventTypes.ResponseDone,
            role=Role.Assistant,
            reason="stop",
            partial=msg,
        )
    )
    backend.push(
        ResponseTextUpdatedEvent(
            type=ServerEventTypes.ResponseTextContentUpdated,
            role=Role.Assistant,
            content_type="text",
            content_index=0,
            partial=msg,
        )
    )
    backend.end()
    await asyncio.sleep(0.05)

    assert len(delivered) == 1
    assert delivered[0].type is SessionEventTypes.ResponseDelta

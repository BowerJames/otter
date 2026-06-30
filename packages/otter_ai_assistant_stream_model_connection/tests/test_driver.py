"""Behavioural tests for the assistant-stream → model-connection driver."""

from __future__ import annotations

import asyncio
from typing import Any

from _adapter_helpers import (
    ScriptedStreamFn,
    done_event,
    drain,
    make_message,
    simple_context,
    start_event,
    take,
    text_block,
    text_delta,
    text_end,
    text_start,
    user_text,
)

from otter_ai_assistant_stream_model_connection import (
    create_assistant_stream_model_connection,
)
from otter_ai_core import TextContent, context_item
from otter_ai_core.model_connection import (
    AbortResponseEvent,
    ConnectionErrorEvent,
    ContextItemAddedEvent,
    ContextItemAddEvent,
    ResponseAbortedEvent,
    ResponseDoneEvent,
    ResponseStartedEvent,
    ResponseTextUpdatedEvent,
)


def _connect(
    fn: ScriptedStreamFn, context: Any, abort: asyncio.Event | None = None
) -> Any:
    if abort is None:
        abort = asyncio.Event()
    return create_assistant_stream_model_connection(fn)(context, abort)


async def test_happy_path_drives_a_turn_and_auto_appends() -> None:
    fn = ScriptedStreamFn()
    context = simple_context()
    conn = _connect(fn, context)

    partial = make_message(content=[text_block("")])
    final = make_message(content=[text_block("Hi there")])
    fn.feed(
        start_event(partial),
        text_start(0, partial),
        text_delta(0, "Hi ", partial),
        text_delta(0, "there", partial),
        text_end(0, "Hi there", partial),
        done_event(final),
    )

    conn.send(_create_response())
    events = await take(conn, 7)

    assert [type(e).__name__ for e in events] == [
        "ResponseStartedEvent",
        "ResponseTextStartEvent",
        "ResponseTextUpdatedEvent",
        "ResponseTextUpdatedEvent",
        "ResponseTextDoneEvent",
        "ResponseDoneEvent",
        "ContextItemAddedEvent",
    ]
    assert events[-2].partial.content[0].text == "Hi there"

    # The final assistant message was auto-appended to the live context.
    assert len(context.items) == 1
    assert context.items[0].to_message() == final

    conn.close()
    await drain(conn)


async def test_idle_context_item_add_mutates_context_and_echoes() -> None:
    fn = ScriptedStreamFn()
    context = simple_context()
    conn = _connect(fn, context)

    item = context_item(user_text("hello"), "user-1")
    conn.send(ContextItemAddEvent(type="context_item.add", item=item))

    events = await take(conn, 1)
    assert isinstance(events[0], ContextItemAddedEvent)
    assert events[0].item_id == "user-1"
    assert events[0].role == "user"
    # The caller-supplied id is echoed (not a generated uuid4).
    assert context.items[-1] is item

    conn.close()
    await drain(conn)


async def test_per_response_abort_aborts_turn_but_keeps_connection_open() -> None:
    fn = ScriptedStreamFn()
    context = simple_context()
    conn = _connect(fn, context)

    partial = make_message(content=[text_block("")])
    fn.feed(start_event(partial), text_start(0, partial))
    conn.send(_create_response())
    await take(conn, 2)  # started + text start

    # Abort only the in-flight response.
    conn.send(AbortResponseEvent(type="response.abort"))
    aborted = await take(conn, 1)
    assert isinstance(aborted[0], ResponseAbortedEvent)
    assert fn.aborts_received == 1
    # The aborted turn is NOT appended.
    assert context.items == []

    # The connection stays open: a second response.create succeeds.
    final = make_message(content=[text_block("again")])
    fn.feed(start_event(make_message()), done_event(final))
    conn.send(_create_response())
    second = await take(conn, 3)  # started + done + context_item_added
    assert isinstance(second[0], ResponseStartedEvent)
    assert any(isinstance(e, ResponseDoneEvent) for e in second)
    assert any(isinstance(e, ContextItemAddedEvent) for e in second)

    conn.close()
    await drain(conn)


async def test_connection_abort_aborts_turn_and_ends_gracefully() -> None:
    fn = ScriptedStreamFn()
    abort = asyncio.Event()
    conn = _connect(fn, simple_context(), abort)

    partial = make_message(content=[text_block("")])
    fn.feed(start_event(partial), text_start(0, partial))
    conn.send(_create_response())
    await take(conn, 2)

    abort.set()
    events = await drain(conn)

    # The in-flight turn surfaces an aborted terminal ...
    assert any(isinstance(e, ResponseAbortedEvent) for e in events)
    # ... but a connection cancel is graceful — no connection-level error.
    assert not any(isinstance(e, ConnectionErrorEvent) for e in events)


async def test_caller_close_ends_gracefully_no_error_event() -> None:
    fn = ScriptedStreamFn()
    conn = _connect(fn, simple_context())

    partial = make_message(content=[text_block("")])
    fn.feed(start_event(partial), text_start(0, partial))
    conn.send(_create_response())
    await take(conn, 2)

    conn.close()
    events = await drain(conn)
    assert not any(isinstance(e, ConnectionErrorEvent) for e in events)


async def test_terminal_and_caller_close_same_cycle_do_not_deadlock() -> None:
    # Regression: when the stream reaches a terminal event AND the caller
    # closes (the outbound ``None`` sentinel) in the same ``asyncio.wait``
    # cycle, the sentinel must still be detected and signal the idle loop to
    # stop. An earlier version guarded the whole client block with
    # ``not terminal``, so a coincident terminal hid the sentinel, left
    # ``connection_ended`` False, and the idle loop started another ``anext``
    # on the already-exhausted outbound stream — hanging forever.
    #
    # The race is made deterministic with an *immediate-terminal* producer:
    # the terminal ``done`` event is the stream's very first event (pushed
    # synchronously before the stream is returned), and ``ResponseCreate`` +
    # the close sentinel are both queued on the backend before the driver runs.
    # The driver then consumes ``ResponseCreate`` (idle), enters the turn, and
    # in the turn's first ``asyncio.wait`` BOTH the stream terminal and the
    # close sentinel resolve in the same cycle.
    from otter_ai_core import create_stream
    from otter_ai_core.assistant_message_stream import AssistantMessageStream

    final = make_message(content=[text_block("done")])

    def immediate_done_stream_fn(
        context: object, abort: object
    ) -> AssistantMessageStream:
        stream: AssistantMessageStream
        writer: object
        stream, writer = create_stream()
        writer.push(done_event(final))  # terminal as the very first event
        return stream

    context = simple_context()
    connection_fn = create_assistant_stream_model_connection(immediate_done_stream_fn)
    conn = connection_fn(context, asyncio.Event())

    # Queue the request AND the close before the driver runs, so the turn's
    # first ``asyncio.wait`` sees both the stream terminal and the sentinel.
    conn.send(_create_response())
    conn.close()

    events = await drain(conn)
    # The clean terminal landed before graceful teardown …
    assert any(isinstance(e, ResponseDoneEvent) for e in events)
    assert any(isinstance(e, ContextItemAddedEvent) for e in events)
    # … and a coincident caller-close is graceful — no connection-level error.
    assert not any(isinstance(e, ConnectionErrorEvent) for e in events)
    # The auto-append still committed the clean turn to the live context.
    assert len(context.items) == 1
    assert context.items[0].to_message() == final


async def test_multi_turn_accumulates_context() -> None:
    fn = ScriptedStreamFn()
    context = simple_context()
    conn = _connect(fn, context)

    # Turn 1.
    final1 = make_message(content=[text_block("one")])
    fn.feed(start_event(make_message()), done_event(final1))
    conn.send(_create_response())
    first = await take(conn, 3)
    assert any(isinstance(e, ResponseDoneEvent) for e in first)

    # Turn 2 — the idle loop owns the channel between turns.
    final2 = make_message(content=[text_block("two")])
    fn.feed(start_event(make_message()), done_event(final2))
    conn.send(_create_response())
    second = await take(conn, 3)
    assert any(isinstance(e, ResponseDoneEvent) for e in second)

    # Both assistant turns were committed to the live context, in order.
    assert len(context.items) == 2
    first_msg = context.items[0].to_message()
    second_msg = context.items[1].to_message()
    first_block = first_msg.content[0]
    second_block = second_msg.content[0]
    assert isinstance(first_block, TextContent)
    assert isinstance(second_block, TextContent)
    assert first_block.text == "one"
    assert second_block.text == "two"

    conn.close()
    await drain(conn)


async def test_text_during_response_is_forwarded_as_updated() -> None:
    fn = ScriptedStreamFn()
    conn = _connect(fn, simple_context())

    partial = make_message(content=[text_block("")])
    fn.feed(
        start_event(partial),
        text_start(0, partial),
        text_delta(0, "Hel", partial),
        text_delta(0, "lo", partial),
    )
    conn.send(_create_response())
    events = await take(conn, 4)
    assert isinstance(events[2], ResponseTextUpdatedEvent)
    assert isinstance(events[3], ResponseTextUpdatedEvent)

    conn.close()
    await drain(conn)


def _create_response() -> Any:
    from otter_ai_core.model_connection import ResponseCreate

    return ResponseCreate(type="response.create")

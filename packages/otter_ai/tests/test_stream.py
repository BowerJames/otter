"""Generic async stream runtime: ordering, termination, idempotency, aliases."""

from __future__ import annotations

import asyncio

from otter_ai import (
    AssistantDoneEvent,
    AssistantMessage,
    AssistantMessageEvent,
    AssistantMessageStream,
    AssistantMessageWriter,
    AssistantStartEvent,
    AssistantTextDeltaEvent,
    AssistantTextStartEvent,
    ContextItemStream,
    ContextItemWriter,
    MessageEvent,
    MessageEventStream,
    MessageEventWriter,
    Stream,
    StreamWriter,
    Usage,
    UsageCost,
    UserMessage,
    UserMessageStream,
    UserMessageWriter,
    create_stream,
)


def _usage() -> Usage:
    return Usage(
        input=10,
        output=5,
        cache_read=0,
        cache_write=0,
        total_tokens=15,
        cost=UsageCost(
            input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0
        ),
    )


def _assistant_message() -> AssistantMessage:
    from otter_ai import TextContent

    return AssistantMessage(
        role="assistant",
        content=[TextContent(type="text", text="hi")],
        api="anthropic-messages",
        provider="anthropic",
        model="claude-3",
        usage=_usage(),
        stop_reason="stop",
        timestamp=1,
    )


def _assistant_events() -> list[AssistantMessageEvent]:
    partial = _assistant_message()
    return [
        AssistantStartEvent(role="assistant", type="start", partial=partial),
        AssistantTextStartEvent(
            role="assistant", type="text_start", content_index=0, partial=partial
        ),
        AssistantTextDeltaEvent(
            role="assistant",
            type="text_delta",
            content_index=0,
            delta="hi",
            partial=partial,
        ),
        AssistantDoneEvent(
            role="assistant", type="done", reason="stop", message=partial
        ),
    ]


async def _collect[TEvent](stream: Stream[TEvent]) -> list[TEvent]:
    return [event async for event in stream]


async def test_events_yielded_in_order_then_terminate() -> None:
    stream: Stream[AssistantMessageEvent]
    writer: StreamWriter[AssistantMessageEvent]
    stream, writer = create_stream()
    events = _assistant_events()
    for event in events:
        writer.push(event)
    writer.end()

    received = await _collect(stream)

    assert received == events
    assert received[-1].type == "done"


async def test_terminal_event_reachable_before_iteration_stops() -> None:
    """The ``done`` event is yielded (its message reachable) before iteration ends."""
    stream: Stream[AssistantMessageEvent]
    writer: StreamWriter[AssistantMessageEvent]
    stream, writer = create_stream()
    events = _assistant_events()
    for event in events:
        writer.push(event)
    writer.end()

    received = await _collect(stream)
    last = received[-1]
    assert isinstance(last, AssistantDoneEvent)
    assert isinstance(last.message, AssistantMessage)


async def test_end_with_no_pushes_yields_nothing() -> None:
    stream: Stream[AssistantMessageEvent]
    writer: StreamWriter[AssistantMessageEvent]
    stream, writer = create_stream()
    writer.end()
    assert await _collect(stream) == []


async def test_push_after_end_is_noop() -> None:
    stream: Stream[AssistantMessageEvent]
    writer: StreamWriter[AssistantMessageEvent]
    stream, writer = create_stream()
    events = _assistant_events()
    writer.end()
    for event in events:
        writer.push(event)  # all dropped

    assert await _collect(stream) == []


async def test_end_is_idempotent() -> None:
    """Calling ``end`` twice does not enqueue an extra sentinel."""
    stream: Stream[AssistantMessageEvent]
    writer: StreamWriter[AssistantMessageEvent]
    stream, writer = create_stream()
    events = _assistant_events()
    for event in events:
        writer.push(event)
    writer.end()
    writer.end()  # second end is a no-op

    received = await _collect(stream)
    assert received == events  # exactly the pushed events, nothing extra


async def test_aclose_unblocks_pending_consumer_and_stops() -> None:
    """Consumer-side ``aclose`` ends iteration from the consumer's side."""
    stream: Stream[AssistantMessageEvent]
    writer: StreamWriter[AssistantMessageEvent]
    stream, writer = create_stream()
    # No events pushed, no end() called: a bare ``async for`` would block.
    # Have the consumer close itself from another task.
    task = asyncio.create_task(_collect(stream))
    await asyncio.sleep(0)  # let the consumer await the empty queue
    await stream.aclose()

    received = await asyncio.wait_for(task, timeout=1.0)
    assert received == []


async def test_aclose_then_push_is_noop() -> None:
    stream: Stream[AssistantMessageEvent]
    writer: StreamWriter[AssistantMessageEvent]
    stream, writer = create_stream()
    await stream.aclose()

    events = _assistant_events()
    for event in events:
        writer.push(event)  # producer closed out from the consumer side

    # Consumer already closed: iteration yields nothing.
    received = await asyncio.wait_for(_collect(stream), timeout=1.0)
    assert received == []


async def test_concurrent_producer_consumer() -> None:
    """Producer pushes from a task while consumer drains concurrently."""
    stream: Stream[AssistantMessageEvent]
    writer: StreamWriter[AssistantMessageEvent]
    stream, writer = create_stream()
    events = _assistant_events()

    async def produce() -> None:
        for event in events:
            writer.push(event)
            await asyncio.sleep(0)
        writer.end()

    producer = asyncio.create_task(produce())
    received = await _collect(stream)
    await producer

    assert received == events


async def test_message_event_stream_carries_assistant_and_user() -> None:
    """``MessageEventStream`` spans assistant + user events (no tool results)."""
    from otter_ai import UserDoneEvent, UserStartEvent

    stream: Stream[MessageEvent]
    writer: StreamWriter[MessageEvent]
    stream, writer = create_stream()
    assistant_partial = _assistant_message()
    user_message = UserMessage(
        role="user",
        content=[{"type": "text", "text": "hello"}],
        timestamp=2,
    )

    a_start: MessageEvent = AssistantStartEvent(
        role="assistant", type="start", partial=assistant_partial
    )
    u_start: MessageEvent = UserStartEvent(
        role="user", type="start", partial=user_message
    )
    a_done: MessageEvent = AssistantDoneEvent(
        role="assistant", type="done", reason="stop", message=assistant_partial
    )
    u_done: MessageEvent = UserDoneEvent(role="user", type="done", message=user_message)

    for event in (a_start, u_start, a_done, u_done):
        writer.push(event)
    writer.end()

    received = await _collect(stream)
    assert [type(e) for e in received] == [
        AssistantStartEvent,
        UserStartEvent,
        AssistantDoneEvent,
        UserDoneEvent,
    ]


def test_type_aliases_are_stream_specializations() -> None:
    """Each typed alias is usable via an annotated ``create_stream()`` unpack."""
    a_stream: AssistantMessageStream
    a_writer: AssistantMessageWriter
    a_stream, a_writer = create_stream()
    assert isinstance(a_stream, Stream)
    assert isinstance(a_writer, StreamWriter)

    u_stream: UserMessageStream
    u_writer: UserMessageWriter
    u_stream, u_writer = create_stream()
    assert isinstance(u_stream, Stream)
    assert isinstance(u_writer, StreamWriter)

    m_stream: MessageEventStream
    m_writer: MessageEventWriter
    m_stream, m_writer = create_stream()
    assert isinstance(m_stream, Stream)
    assert isinstance(m_writer, StreamWriter)

    c_stream: ContextItemStream
    c_writer: ContextItemWriter
    c_stream, c_writer = create_stream()
    assert isinstance(c_stream, Stream)
    assert isinstance(c_writer, StreamWriter)


def test_assistant_message_stream_fn_accepts_conforming_callable() -> None:
    """``AssistantMessageStreamFn`` is the producer-side seam type.

    mypy is the real enforcer; this just checks the alias is importable and a
    trivially-conforming two-argument function binds under an annotation
    referencing it.
    """
    from otter_ai import (
        AssistantMessageStreamFn,
        Context,
    )

    def make_stream(model: object, context: Context) -> AssistantMessageStream:
        stream: AssistantMessageStream
        _writer: AssistantMessageWriter
        stream, _writer = create_stream()
        return stream

    fn: AssistantMessageStreamFn[object] = make_stream
    assert callable(fn)

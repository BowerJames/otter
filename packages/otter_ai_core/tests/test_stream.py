"""Generic async stream runtime: ordering, termination, idempotency, aliases."""

from __future__ import annotations

import asyncio

from otter_ai_core import (
    AssistantMessage,
    Stream,
    StreamWriter,
    Usage,
    UsageCost,
    create_stream,
)
from otter_ai_core.assistant_message_stream import (
    AssistantDoneEvent,
    AssistantMessageEvent,
    AssistantMessageStream,
    AssistantMessageWriter,
    AssistantStartEvent,
    AssistantTextDeltaEvent,
    AssistantTextStartEvent,
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
    from otter_ai_core import TextContent

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


def test_type_aliases_are_stream_specializations() -> None:
    """The assistant alias is usable via an annotated ``create_stream()`` unpack."""
    a_stream: AssistantMessageStream
    a_writer: AssistantMessageWriter
    a_stream, a_writer = create_stream()
    assert isinstance(a_stream, Stream)
    assert isinstance(a_writer, StreamWriter)


def test_assistant_message_stream_fn_builder_returns_conforming_callable() -> None:
    """``AssistantMessageStreamFnBuilder`` is the producer-side seam type.

    mypy is the real enforcer; this just checks the alias is importable and a
    trivially-conforming builder — ``(options) -> AssistantMessageStreamFn`` —
    binds under an annotation referencing it, and that the returned fn has the
    options-bound ``(context, abort) -> stream`` shape.
    """
    from otter_ai_core import Context
    from otter_ai_core.assistant_message_stream import (
        AssistantMessageStreamFn,
        AssistantMessageStreamFnBuilder,
    )

    def make_stream_fn(options: object) -> AssistantMessageStreamFn:
        del options

        def stream_fn(context: Context, abort: asyncio.Event) -> AssistantMessageStream:
            del context, abort
            stream: AssistantMessageStream
            _writer: AssistantMessageWriter
            stream, _writer = create_stream()
            return stream

        return stream_fn

    builder: AssistantMessageStreamFnBuilder[object] = make_stream_fn
    assert callable(builder)
    fn = builder(object())
    assert callable(fn)

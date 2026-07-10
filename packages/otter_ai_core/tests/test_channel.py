"""Generic async channel runtime: ordering, termination, idempotency, aliases."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, fields

import pytest

from otter_ai_core import (
    AssistantMessage,
    ChannelPair,
    ChannelReader,
    ChannelWriter,
    Usage,
    UsageCost,
    create_channel,
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


async def _collect[TEvent](reader: ChannelReader[TEvent]) -> list[TEvent]:
    return [event async for event in reader]


async def test_events_yielded_in_order_then_terminate() -> None:
    wiring: ChannelPair[AssistantMessageEvent] = create_channel()
    stream = wiring.reader
    writer = wiring.writer
    events = _assistant_events()
    for event in events:
        writer.push(event)
    writer.end()

    received = await _collect(stream)

    assert received == events
    assert received[-1].type == "done"


async def test_terminal_event_reachable_before_iteration_stops() -> None:
    """The ``done`` event is yielded (its message reachable) before iteration ends."""
    wiring: ChannelPair[AssistantMessageEvent] = create_channel()
    stream = wiring.reader
    writer = wiring.writer
    events = _assistant_events()
    for event in events:
        writer.push(event)
    writer.end()

    received = await _collect(stream)
    last = received[-1]
    assert isinstance(last, AssistantDoneEvent)
    assert isinstance(last.message, AssistantMessage)


async def test_end_with_no_pushes_yields_nothing() -> None:
    wiring: ChannelPair[AssistantMessageEvent] = create_channel()
    stream = wiring.reader
    writer = wiring.writer
    writer.end()
    assert await _collect(stream) == []


async def test_push_after_end_is_noop() -> None:
    wiring: ChannelPair[AssistantMessageEvent] = create_channel()
    stream = wiring.reader
    writer = wiring.writer
    events = _assistant_events()
    writer.end()
    for event in events:
        writer.push(event)  # all dropped

    assert await _collect(stream) == []


async def test_end_is_idempotent() -> None:
    """Calling ``end`` twice does not enqueue an extra sentinel."""
    wiring: ChannelPair[AssistantMessageEvent] = create_channel()
    stream = wiring.reader
    writer = wiring.writer
    events = _assistant_events()
    for event in events:
        writer.push(event)
    writer.end()
    writer.end()  # second end is a no-op

    received = await _collect(stream)
    assert received == events  # exactly the pushed events, nothing extra


async def test_concurrent_producer_consumer() -> None:
    """Producer pushes from a task while consumer drains concurrently."""
    wiring: ChannelPair[AssistantMessageEvent] = create_channel()
    stream = wiring.reader
    writer = wiring.writer
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


async def test_reader_is_single_pass() -> None:
    """The read end may be iterated at most once; a second pass raises."""
    wiring: ChannelPair[AssistantMessageEvent] = create_channel()
    reader = wiring.reader
    writer = wiring.writer
    events = _assistant_events()
    for event in events:
        writer.push(event)
    writer.end()

    assert await _collect(reader) == events  # first iteration: OK

    with pytest.raises(RuntimeError):
        async for _ in reader:  # second pass rejected (single-consumer)
            pass


def test_type_aliases_are_channel_specializations() -> None:
    """The assistant alias is usable via an annotated ``create_channel()`` unpack."""
    wiring: ChannelPair[AssistantMessageEvent] = create_channel()
    a_stream: AssistantMessageStream = wiring.reader
    a_writer: AssistantMessageWriter = wiring.writer
    assert isinstance(a_stream, ChannelReader)
    assert isinstance(a_writer, ChannelWriter)


def test_create_channel_returns_channel_pair_with_named_fields() -> None:
    """``create_channel()`` returns a frozen ``ChannelPair`` (writer, reader).

    Field order is ``writer`` (the ``ChannelWriter``) then ``reader`` (the
    ``ChannelReader``), and the pair is frozen. Re-exported from the top-level
    ``otter_ai_core`` namespace.
    """
    from otter_ai_core import ChannelPair as TopLevelChannelWiring

    wiring: ChannelPair[AssistantMessageEvent] = create_channel()
    assert isinstance(wiring, ChannelPair)
    assert TopLevelChannelWiring is ChannelPair  # re-exported at top level
    # Field order: writer first, reader second.
    assert [f.name for f in fields(wiring)] == ["writer", "reader"]
    assert isinstance(wiring.writer, ChannelWriter)
    assert isinstance(wiring.reader, ChannelReader)
    # Frozen: attribute assignment is rejected.
    with pytest.raises(FrozenInstanceError):
        wiring.reader = wiring.reader  # type: ignore[misc]


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
            wiring: ChannelPair[AssistantMessageEvent] = create_channel()
            stream: AssistantMessageStream = wiring.reader
            return stream

        return stream_fn

    builder: AssistantMessageStreamFnBuilder[object] = make_stream_fn
    assert callable(builder)
    fn = builder(object())
    assert callable(fn)

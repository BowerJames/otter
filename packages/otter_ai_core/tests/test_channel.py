"""Generic async channel runtime: ordering, termination, idempotency, aliases."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, fields

import pytest

from otter_ai_core import (
    ChannelPair,
    ChannelReader,
    ChannelWriter,
    create_channel,
)
from tests._dummy_event import DummyEvent, DummyEventType, dummy_events


async def _collect[TEvent](reader: ChannelReader[TEvent]) -> list[TEvent]:
    return [event async for event in reader]


async def test_events_yielded_in_order_then_terminate() -> None:
    wiring: ChannelPair[DummyEvent] = create_channel()
    stream = wiring.reader
    writer = wiring.writer
    events = dummy_events()
    for event in events:
        writer.push(event)
    writer.end()

    received = await _collect(stream)

    assert received == events
    assert received[-1].type == DummyEventType.DONE


async def test_terminal_event_reachable_before_iteration_stops() -> None:
    """The terminal event is yielded (its payload reachable) before iteration ends."""
    wiring: ChannelPair[DummyEvent] = create_channel()
    stream = wiring.reader
    writer = wiring.writer
    events = dummy_events()
    for event in events:
        writer.push(event)
    writer.end()

    received = await _collect(stream)
    last = received[-1]
    assert last.type is DummyEventType.DONE


async def test_end_with_no_pushes_yields_nothing() -> None:
    wiring: ChannelPair[DummyEvent] = create_channel()
    stream = wiring.reader
    writer = wiring.writer
    writer.end()
    assert await _collect(stream) == []


async def test_push_after_end_is_noop() -> None:
    wiring: ChannelPair[DummyEvent] = create_channel()
    stream = wiring.reader
    writer = wiring.writer
    events = dummy_events()
    writer.end()
    for event in events:
        writer.push(event)  # all dropped

    assert await _collect(stream) == []


async def test_end_is_idempotent() -> None:
    """Calling ``end`` twice does not enqueue an extra sentinel."""
    wiring: ChannelPair[DummyEvent] = create_channel()
    stream = wiring.reader
    writer = wiring.writer
    events = dummy_events()
    for event in events:
        writer.push(event)
    writer.end()
    writer.end()  # second end is a no-op

    received = await _collect(stream)
    assert received == events  # exactly the pushed events, nothing extra


async def test_concurrent_producer_consumer() -> None:
    """Producer pushes from a task while consumer drains concurrently."""
    wiring: ChannelPair[DummyEvent] = create_channel()
    stream = wiring.reader
    writer = wiring.writer
    events = dummy_events()

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
    wiring: ChannelPair[DummyEvent] = create_channel()
    reader = wiring.reader
    writer = wiring.writer
    events = dummy_events()
    for event in events:
        writer.push(event)
    writer.end()

    assert await _collect(reader) == events  # first iteration: OK

    with pytest.raises(RuntimeError):
        async for _ in reader:  # second pass rejected (single-consumer)
            pass


def test_create_channel_returns_channel_pair_with_named_fields() -> None:
    """``create_channel()`` returns a frozen ``ChannelPair`` (writer, reader).

    Field order is ``writer`` (the ``ChannelWriter``) then ``reader`` (the
    ``ChannelReader``), and the pair is frozen. Re-exported from the top-level
    ``otter_ai_core`` namespace.
    """
    from otter_ai_core import ChannelPair as TopLevelChannelWiring

    wiring: ChannelPair[DummyEvent] = create_channel()
    assert isinstance(wiring, ChannelPair)
    assert TopLevelChannelWiring is ChannelPair  # re-exported at top level
    # Field order: writer first, reader second.
    assert [f.name for f in fields(wiring)] == ["writer", "reader"]
    assert isinstance(wiring.writer, ChannelWriter)
    assert isinstance(wiring.reader, ChannelReader)
    # Frozen: attribute assignment is rejected.
    with pytest.raises(FrozenInstanceError):
        wiring.reader = wiring.reader  # type: ignore[misc]

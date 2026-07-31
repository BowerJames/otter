"""Default Channel: self-contained asyncio.Queue-backed one-way self-loop."""

from __future__ import annotations

import asyncio

import pytest

from otter_ai_core import DefaultChannel, create_default_channel
from otter_ai_core.interfaces import Channel
from tests._dummy_event import DummyEvent, DummyEventType, dummy_events


async def _collect[TEvent](channel: Channel[TEvent]) -> list[TEvent]:
    return [event async for event in channel]


async def test_events_yielded_in_order_then_terminate() -> None:
    channel: DefaultChannel[DummyEvent] = DefaultChannel()
    events = dummy_events()
    for event in events:
        channel.push(event)
    channel.end()

    received = await _collect(channel)

    assert received == events
    assert received[-1].type == DummyEventType.DONE


async def test_end_with_no_pushes_yields_nothing() -> None:
    channel: DefaultChannel[DummyEvent] = DefaultChannel()
    channel.end()
    assert await _collect(channel) == []


async def test_push_after_end_is_noop() -> None:
    channel: DefaultChannel[DummyEvent] = DefaultChannel()
    events = dummy_events()
    channel.end()
    for event in events:
        channel.push(event)  # all dropped

    assert await _collect(channel) == []


async def test_end_is_idempotent() -> None:
    """Calling ``end`` twice does not enqueue an extra sentinel."""
    channel: DefaultChannel[DummyEvent] = DefaultChannel()
    events = dummy_events()
    for event in events:
        channel.push(event)
    channel.end()
    channel.end()  # second end is a no-op

    received = await _collect(channel)
    assert received == events  # exactly the pushed events, nothing extra


async def test_concurrent_producer_consumer() -> None:
    """Producer pushes from a task while the consumer drains concurrently."""
    channel: DefaultChannel[DummyEvent] = DefaultChannel()
    events = dummy_events()

    async def produce() -> None:
        for event in events:
            channel.push(event)
            await asyncio.sleep(0)
        channel.end()

    producer = asyncio.create_task(produce())
    received = await _collect(channel)
    await producer

    assert received == events


async def test_channel_is_single_pass() -> None:
    """The channel may be iterated at most once; a second pass raises."""
    channel: DefaultChannel[DummyEvent] = DefaultChannel()
    events = dummy_events()
    for event in events:
        channel.push(event)
    channel.end()

    assert await _collect(channel) == events  # first iteration: OK

    with pytest.raises(RuntimeError):
        async for _ in channel:  # second pass rejected (single-pass)
            pass


async def test_events_buffered_before_iteration_start() -> None:
    """Events pushed before any consumer iterates buffer on the queue and drain
    in order once iteration begins (no live consumer is required to push)."""
    channel: DefaultChannel[DummyEvent] = DefaultChannel()
    events = dummy_events()
    for event in events:
        channel.push(event)
    await asyncio.sleep(0.01)  # nothing iterating yet: just buffered
    channel.end()

    received = await _collect(channel)
    assert received == events


async def test_create_default_channel_returns_working_channel() -> None:
    channel: Channel[DummyEvent] = create_default_channel()
    events = dummy_events()
    for event in events:
        channel.push(event)
    channel.end()

    received = await _collect(channel)
    assert received == events

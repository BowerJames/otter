"""Generic async bidirectional-channel runtime: flow, termination, lifecycle."""

from __future__ import annotations

import asyncio

from otter_ai_core import (
    BidirectionalChannelBackend,
    BidirectionalChannelClient,
    BidirectionalChannelPair,
    create_bidirectional_channel,
)


def _new() -> tuple[BidirectionalChannelClient[str, int], BidirectionalChannelBackend[str, int]]:
    """A typed client/backend pair for the common (str, int) event shapes.

    Locals are annotated so ``create_bidirectional_channel()`` is called bare
    (PEP 695 generic functions are not subscriptable at runtime), mirroring
    ``test_channel.py``'s use of ``create_channel()``.
    """
    pair: BidirectionalChannelPair[str, int]
    pair = create_bidirectional_channel()
    return pair.client, pair.backend


async def _drain(backend: BidirectionalChannelBackend[str, int]) -> list[str]:
    """Collect every outbound client event the client pushed, in order."""
    return [event async for event in backend]


async def test_inbound_events_flow_to_client_in_order() -> None:
    """``backend.push`` events are observed by ``async for`` over the channel."""
    client, backend = _new()
    for event in (1, 2, 3):
        backend.push(event)
    backend.end()

    received = [event async for event in client]

    assert received == [1, 2, 3]


async def test_outbound_events_flow_to_backend_in_order() -> None:
    """``client.push`` events are drained in push order by the backend."""
    client, backend = _new()

    async def call() -> None:
        for event in ("a", "b", "c"):
            client.push(event)
            await asyncio.sleep(0)
        client.end()

    sender = asyncio.create_task(call())
    received = await _drain(backend)
    await sender

    assert received == ["a", "b", "c"]


async def test_client_end_ends_outbound_then_backend_ends_inbound() -> None:
    """The ``None`` sentinel carries the end across both directions.

    Client ``end`` ends the outbound writer; the backend's drain stops; the
    backend then calls ``end`` and the client's inbound iteration stops.
    """
    client, backend = _new()

    async def backend_task() -> None:
        # Drain until the client ends outbound.
        drained = [event async for event in backend]
        assert drained == ["only"]
        backend.push(99)
        backend.end()

    task = asyncio.create_task(backend_task())

    client.push("only")
    client.end()

    received = [event async for event in client]
    await task

    assert received == [99]


async def test_backend_end_terminates_client_iteration() -> None:
    """``backend.end`` stops the client's inbound iteration."""
    client, backend = _new()
    backend.push(7)
    backend.end()

    received = [event async for event in client]
    assert received == [7]


async def test_client_push_after_end_is_noop() -> None:
    """Pushes after ``client.end`` are dropped (delegates to ``ChannelWriter.push``)."""
    client, backend = _new()
    client.push("kept")
    client.end()
    client.push("dropped")

    received = await _drain(backend)
    assert received == ["kept"]


async def test_backend_push_after_end_is_noop() -> None:
    """Pushes after ``backend.end`` are dropped."""
    client, backend = _new()
    backend.push(1)
    backend.end()
    backend.push(2)  # dropped

    received = [event async for event in client]
    assert received == [1]


async def test_client_end_is_idempotent() -> None:
    """A second ``client.end`` does not enqueue an extra sentinel."""
    client, backend = _new()
    client.push("x")
    client.end()
    client.end()

    received = await _drain(backend)
    assert received == ["x"]


async def test_backend_end_is_idempotent() -> None:
    """A second ``backend.end`` does not enqueue an extra sentinel."""
    client, backend = _new()
    backend.push(1)
    backend.end()
    backend.end()

    received = [event async for event in client]
    assert received == [1]


async def test_bidirectional_concurrent() -> None:
    """Client pushes while backend pushes, both directions live at once."""
    client, backend = _new()

    async def client_side() -> list[int]:
        client.push("ping")
        client.end()  # signal no more outbound so the server's drain completes
        received = [event async for event in client]
        return received

    async def server() -> None:
        client_events = [event async for event in backend]
        assert client_events == ["ping"]
        backend.push(1)
        backend.push(2)
        backend.end()

    server_task = asyncio.create_task(server())
    received = await client_side()
    await server_task

    assert received == [1, 2]


async def test_create_bidirectional_channel_returns_paired_ends() -> None:
    """The pair's two ends are the cross-wired client/backend handles."""
    pair: BidirectionalChannelPair[str, int]
    pair = create_bidirectional_channel()
    assert isinstance(pair.client, BidirectionalChannelClient)
    assert isinstance(pair.backend, BidirectionalChannelBackend)

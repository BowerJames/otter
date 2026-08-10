"""Generic abortable connection runtime: iteration, push, abort, pairing, lifecycle."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, fields

import pytest

from otter_ai_core.interfaces.capabilities import BinaryStateMachine
from tests._connection import (
    ConnectionBackend,
    ConnectionClient,
    ConnectionPair,
    create_connection,
)


def _new() -> tuple[ConnectionClient[str, int], ConnectionBackend[str, int]]:
    """A typed client/backend pair for the common (str, int) event shapes.

    Locals are annotated so ``create_connection()`` is called bare (PEP 695
    generic functions are not subscriptable at runtime), mirroring
    ``test_channel.py``'s use of ``create_channel()``.
    """
    pair: ConnectionPair[str, int] = create_connection()
    return pair.client, pair.backend


# --------------------------------------------------------------------------- #
# create_connection: pairing + shared abort signal
# --------------------------------------------------------------------------- #


def test_create_connection_returns_pair_with_named_fields() -> None:
    """``create_connection()`` returns a frozen ``ConnectionPair`` (client, backend)."""
    pair: ConnectionPair[str, int] = create_connection()

    assert isinstance(pair.client, ConnectionClient)
    assert isinstance(pair.backend, ConnectionBackend)
    with pytest.raises(FrozenInstanceError):
        pair.client = pair.client  # type: ignore[misc]
    assert {f.name for f in fields(ConnectionPair)} == {"client", "backend"}


def test_client_and_backend_share_one_abort_signal() -> None:
    """The abort signal set by the client is the one the backend observes."""
    pair: ConnectionPair[str, int] = create_connection()

    assert not pair.backend.abort_signal.is_set()
    pair.client.abort()
    assert pair.backend.abort_signal.is_set()


def test_abort_is_idempotent() -> None:
    pair: ConnectionPair[str, int] = create_connection()
    pair.client.abort()
    pair.client.abort()  # second set is a no-op, not an error
    assert pair.backend.abort_signal.is_set()


def test_distinct_pairs_have_distinct_signals() -> None:
    a: ConnectionPair[str, int] = create_connection()
    b: ConnectionPair[str, int] = create_connection()
    a.client.abort()
    assert a.backend.abort_signal.is_set()
    assert not b.backend.abort_signal.is_set()


# --------------------------------------------------------------------------- #
# end() terminates (closes the outbound); abort() is graceful (signal only)
# --------------------------------------------------------------------------- #


async def test_end_closes_outbound_so_backend_drain_completes() -> None:
    """``client.end()`` sets the signal **and** ends the outbound writer.

    So a backend draining the outbound over ``async for`` terminates (it does
    not hang waiting for events the ended client will never send).
    """
    pair: ConnectionPair[str, int] = create_connection()
    pair.client.push("x")
    pair.client.end()

    drained = [event async for event in pair.backend]  # drains outbound, then stops
    assert drained == ["x"]
    assert pair.backend.abort_signal.is_set()


async def test_abort_does_not_close_outbound() -> None:
    """``client.abort()`` is graceful: it sets the signal but leaves the outbound
    open, so a backend draining the outbound does not terminate on its own."""
    pair: ConnectionPair[str, int] = create_connection()
    pair.client.push("x")
    pair.client.abort()

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            async for _event in pair.backend:
                pass
    assert pair.backend.abort_signal.is_set()


# --------------------------------------------------------------------------- #
# BinaryStateMachine: is_idle / wait_for_idle (wire-driven via a classifier)
# --------------------------------------------------------------------------- #


def _connection_client_satisfies_binary_state_machine(
    client: ConnectionClient[str, int],
) -> BinaryStateMachine:
    return client


async def test_connection_starts_idle() -> None:
    pair: ConnectionPair[str, int] = create_connection()
    assert pair.client.is_idle() is True
    await asyncio.wait_for(pair.client.wait_for_idle(), 1)  # already idle -> returns


async def test_wire_latch_flips_busy_then_idle() -> None:
    def classify(event: int) -> bool | None:
        if event == 1:
            return True
        if event == 2:
            return False
        return None

    pair: ConnectionPair[str, int] = create_connection(classify=classify)
    assert pair.client.is_idle() is True
    pair.backend.push(1)
    pair.backend.push(2)
    pair.backend.end()

    iterator = aiter(pair.client)
    first = await anext(iterator)
    assert first == 1
    assert pair.client.is_idle() is False  # busy after the start event
    second = await anext(iterator)
    assert second == 2
    assert pair.client.is_idle() is True  # idle after the done event


async def test_wait_for_idle_blocks_until_done_event() -> None:
    def classify(event: int) -> bool | None:
        if event == 1:
            return True
        if event == 2:
            return False
        return None

    pair: ConnectionPair[str, int] = create_connection(classify=classify)
    pair.backend.push(1)
    pair.backend.push(2)

    iterator = aiter(pair.client)
    await anext(iterator)  # 1 -> busy
    assert pair.client.is_idle() is False

    waiter = asyncio.create_task(pair.client.wait_for_idle())
    await asyncio.sleep(0)  # let the waiter park on the idle event
    assert waiter.done() is False
    await anext(iterator)  # 2 -> idle
    await asyncio.wait_for(waiter, 1)


async def test_abort_signal_can_be_awaited_by_producer() -> None:
    """A producer task can ``await backend.wait_for_abort()`` and resolve."""
    pair: ConnectionPair[str, int] = create_connection()

    async def producer() -> None:
        await pair.backend.wait_for_abort()
        pair.backend.push(99)
        pair.backend.end()

    task = asyncio.create_task(producer())
    await asyncio.sleep(0)  # let the producer park on the wait
    assert not task.done()
    pair.client.abort()
    await task

    seen = [event async for event in pair.client]
    assert seen == [99]


# --------------------------------------------------------------------------- #
# Bidirectional flow: backend.push → client; client.push → backend
# --------------------------------------------------------------------------- #


async def test_backend_push_drives_client_iteration() -> None:
    """Inbound events pushed on the backend are read by iterating the client."""
    pair: ConnectionPair[str, int] = create_connection()
    pair.backend.push(1)
    pair.backend.push(2)
    pair.backend.end()

    seen = [event async for event in pair.client]
    assert seen == [1, 2]


async def test_client_push_drives_backend_iteration() -> None:
    """Outbound events pushed on the client are drained in order by the backend."""
    pair: ConnectionPair[str, int] = create_connection()

    async def call() -> None:
        for event in ("a", "b"):
            pair.client.push(event)
            await asyncio.sleep(0)
        pair.client.end()

    sender = asyncio.create_task(call())
    received = [event async for event in pair.backend]
    await sender

    assert received == ["a", "b"]


async def test_concurrent_bidirectional() -> None:
    """Client pushes while backend pushes, both directions live at once."""
    pair: ConnectionPair[str, int] = create_connection()

    async def client() -> list[int]:
        pair.client.push("ping")
        pair.client.end()  # signal no more outbound so the server's drain completes
        received = [event async for event in pair.client]
        return received

    async def server() -> None:
        client_events = [event async for event in pair.backend]
        assert client_events == ["ping"]
        pair.backend.push(1)
        pair.backend.push(2)
        pair.backend.end()

    server_task = asyncio.create_task(server())
    received = await client()
    await server_task

    assert received == [1, 2]


# --------------------------------------------------------------------------- #
# end / push lifecycle: idempotent end, no-op push-after-end (both sides)
# --------------------------------------------------------------------------- #


async def test_backend_end_terminates_client_iteration() -> None:
    """``backend.end`` stops the client's inbound iteration."""
    pair: ConnectionPair[str, int] = create_connection()
    pair.backend.push(7)
    pair.backend.end()

    seen = [event async for event in pair.client]
    assert seen == [7]


async def test_backend_push_after_end_is_noop() -> None:
    pair: ConnectionPair[str, int] = create_connection()
    pair.backend.push(1)
    pair.backend.end()
    pair.backend.push(2)  # dropped

    seen = [event async for event in pair.client]
    assert seen == [1]


async def test_client_push_after_end_is_noop() -> None:
    pair: ConnectionPair[str, int] = create_connection()
    pair.client.push("kept")
    pair.client.end()
    pair.client.push("dropped")

    received = [event async for event in pair.backend]
    assert received == ["kept"]


async def test_backend_end_is_idempotent() -> None:
    pair: ConnectionPair[str, int] = create_connection()
    pair.backend.push(1)
    pair.backend.end()
    pair.backend.end()

    seen = [event async for event in pair.client]
    assert seen == [1]


async def test_client_end_is_idempotent() -> None:
    pair: ConnectionPair[str, int] = create_connection()
    pair.client.push("x")
    pair.client.end()
    pair.client.end()

    received = [event async for event in pair.backend]
    assert received == ["x"]


# --------------------------------------------------------------------------- #
# Single-pass iteration guard (honored on both ends)
# --------------------------------------------------------------------------- #


async def test_second_client_iteration_raises() -> None:
    """A second ``async for`` on the client raises (single-pass via reader)."""
    pair: ConnectionPair[str, int] = create_connection()
    pair.backend.push(1)
    pair.backend.end()

    async for _event in pair.client:
        pass
    with pytest.raises(RuntimeError, match="single-consumer"):
        async for _event in pair.client:
            pass


async def test_second_backend_iteration_raises() -> None:
    """A second ``async for`` on the backend raises (single-pass via reader)."""
    pair: ConnectionPair[str, int] = create_connection()
    pair.client.push("x")
    pair.client.end()

    async for _event in pair.backend:
        pass
    with pytest.raises(RuntimeError, match="single-consumer"):
        async for _event in pair.backend:
            pass

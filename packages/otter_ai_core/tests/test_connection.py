"""Generic async connection runtime: bidirectional flow, termination, lifecycle."""

from __future__ import annotations

import asyncio

from otter_ai_core import Connection, ConnectionBackend, Context, create_connection
from otter_ai_core.connection import ConnectionFn


def _new() -> tuple[Connection[str, int], ConnectionBackend[str, int]]:
    """A typed connection/end pair for the common (str, int) event shapes.

    Locals are annotated so ``create_connection()`` is called bare (PEP 695
    generic functions are not subscriptable at runtime), mirroring
    ``test_stream.py``'s use of ``create_stream()``.
    """
    conn: Connection[str, int]
    backend: ConnectionBackend[str, int]
    conn, backend = create_connection()
    return conn, backend


async def _drain(backend: ConnectionBackend[str, int]) -> list[str]:
    """Collect every outbound client event the caller sent, in order."""
    return [event async for event in backend]


async def test_inbound_events_flow_to_caller_in_order() -> None:
    """``backend.push`` events are observed by ``async for`` over the connection."""
    conn, backend = _new()
    for event in (1, 2, 3):
        backend.push(event)
    backend.end()

    received = [event async for event in conn]

    assert received == [1, 2, 3]


async def test_outbound_events_flow_to_backend_in_order() -> None:
    """``conn.send`` events are drained in send order by the backend."""
    conn, backend = _new()

    async def call() -> None:
        for event in ("a", "b", "c"):
            conn.send(event)
            await asyncio.sleep(0)
        conn.close()

    sender = asyncio.create_task(call())
    received = await _drain(backend)
    await sender

    assert received == ["a", "b", "c"]


async def test_caller_close_ends_outbound_then_backend_ends_inbound() -> None:
    """The ``None`` sentinel carries the close across both directions.

    Caller ``close`` ends the outbound writer; the backend's drain stops; the
    backend then calls ``end`` and the caller's inbound iteration stops.
    """
    conn, backend = _new()

    async def backend_task() -> None:
        # Drain until the caller closes outbound.
        drained = [event async for event in backend]
        assert drained == ["only"]
        backend.push(99)
        backend.end()

    task = asyncio.create_task(backend_task())

    conn.send("only")
    conn.close()

    received = [event async for event in conn]
    await task

    assert received == [99]


async def test_backend_end_terminates_caller_iteration() -> None:
    """``backend.end`` stops the caller's inbound iteration."""
    conn, backend = _new()
    backend.push(7)
    backend.end()

    received = [event async for event in conn]
    assert received == [7]


async def test_send_after_close_is_noop() -> None:
    """Sends after ``close`` are dropped (delegates to ``StreamWriter.push``)."""
    conn, backend = _new()
    conn.send("kept")
    conn.close()
    conn.send("dropped")

    received = await _drain(backend)
    assert received == ["kept"]


async def test_push_after_end_is_noop() -> None:
    """Pushes after ``backend.end`` are dropped."""
    conn, backend = _new()
    backend.push(1)
    backend.end()
    backend.push(2)  # dropped

    received = [event async for event in conn]
    assert received == [1]


async def test_close_is_idempotent() -> None:
    """A second ``close`` does not enqueue an extra sentinel."""
    conn, backend = _new()
    conn.send("x")
    conn.close()
    conn.close()

    received = await _drain(backend)
    assert received == ["x"]


async def test_end_is_idempotent() -> None:
    """A second ``backend.end`` does not enqueue an extra sentinel."""
    conn, backend = _new()
    backend.push(1)
    backend.end()
    backend.end()

    received = [event async for event in conn]
    assert received == [1]


async def test_bidirectional_concurrent() -> None:
    """Caller sends while backend pushes, both directions live at once."""
    conn, backend = _new()

    async def caller() -> list[int]:
        conn.send("ping")
        conn.close()  # signal no more outbound so the server's drain completes
        received = [event async for event in conn]
        return received

    async def server() -> None:
        client_events = [event async for event in backend]
        assert client_events == ["ping"]
        backend.push(1)
        backend.push(2)
        backend.end()

    server_task = asyncio.create_task(server())
    received = await caller()
    await server_task

    assert received == [1, 2]


async def test_create_connection_returns_paired_ends() -> None:
    """The two returned ends are the cross-wired caller/backend handles."""
    conn, backend = _new()
    assert isinstance(conn, Connection)
    assert isinstance(backend, ConnectionBackend)


def test_connection_fn_accepts_conforming_callable() -> None:
    """``ConnectionFn`` is the bidirectional peer seam type.

    mypy is the real enforcer; this checks the alias is importable and a
    trivially-conforming callable binds under an annotation referencing it.
    ``ConnectionFn`` is the *options-bound* producer
    (``Callable[[Context, asyncio.Event], Connection[TClient, TEvent]]``);
    its builder peer is :data:`ModelConnectionFnBuilder`.
    """
    conn: Connection[str, int]
    conn, _backend = create_connection()

    def make_connection(context: Context, abort: asyncio.Event) -> Connection[str, int]:
        inner: Connection[str, int]
        inner, _ = create_connection()
        return inner

    fn: ConnectionFn[str, int] = make_connection
    assert callable(fn)
    assert isinstance(conn, Connection)

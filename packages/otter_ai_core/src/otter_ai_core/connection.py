"""Generic async bidirectional connection runtime.

A :class:`Connection` is a bidirectional channel between a caller and an async
producer (the *backend*, typically a transport-pump task): the caller sends
outbound client events and iterates inbound server events, while the backend
pushes inbound server events and drains outbound client events.

It is a thin composition of two
:func:`~otter_ai_core.stream.create_stream` push-queues, cross-wired one per
direction — there is no new queue or concurrency machinery here. A
unidirectional :class:`~otter_ai_core.stream.Stream` pairs a consumer with a
producer over a single queue; a :class:`Connection` pairs a caller with a
backend over **two** queues, one carrying server→caller events (``TEvent``)
and one carrying caller→server events (``TClient``).

The split mirrors :func:`~otter_ai_core.stream.create_stream`'s
consumer/producer split, generalised to two directions. The caller holds a
:class:`Connection` — it iterates inbound ``TEvent`` s and sends outbound
``TClient`` s. A transport-pump task holds the matching
:class:`ConnectionBackend` — it pushes inbound ``TEvent`` s and drains
outbound ``TClient`` s.

Lifecycle
---------
The connection reuses :class:`~otter_ai_core.stream.StreamWriter`'s ``None``
termination sentinel — there is no separate teardown handshake:

* **Caller closes** — :meth:`Connection.close` ends the outbound writer. The
  backend's drain loop observes end-of-stream (the caller has no more client
  events), tears down its transport, and calls
  :meth:`ConnectionBackend.end`, which ends the inbound writer. The caller
  observes completion when its inbound iteration stops.
* **Server closes** — the backend detects transport EOF and calls
  :meth:`ConnectionBackend.end`; the caller's inbound iteration stops.
* **Connect/transport failure** — the backend task, which owns the transport
  lifecycle (as the chat-completions producer owns its httpx client), encodes
  the failure however its typed event union allows, then ends the inbound
  writer. Because ``TEvent`` is generic, *core* cannot prescribe an
  error-event shape; a typed specialisation (e.g. ``model_connection``)
  supplies it.

``close`` and ``send`` are synchronous (they enqueue / signal, matching
:class:`~otter_ai_core.stream.StreamWriter.push` / ``.end``); the async
transport teardown is the backend task's concern. There is no ``aclose`` — a
caller that wants to await full teardown drains its inbound stream to
completion after closing.

Scope
-----
Otter defines **no transports, providers, API registry, or dispatch** here —
only the generic bidirectional runtime and the :data:`ConnectionFn` seam
type. A typed ``Connection[ClientEvent, ServerEvent]`` alias and a typed seam
alias belong in the specialising subpackage (e.g. ``model_connection``),
mirroring how
:class:`~otter_ai_core.assistant_message_stream.AssistantMessageStream`
specialises :class:`~otter_ai_core.stream.Stream`. Like the stream runtime,
:class:`Connection` and :class:`ConnectionBackend` are runtime objects and
are **not** JSON-serializable.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Self

from otter_ai_core.context import Context
from otter_ai_core.stream import Stream, StreamWriter, create_stream


class Connection[TClient, TEvent]:
    """Caller side of a bidirectional connection.

    Iterate with ``async for event in conn`` to receive inbound server events;
    call :meth:`send` to enqueue an outbound client event; call :meth:`close`
    to signal that no more client events will be sent. The connection is a
    thin facade over an inbound :class:`~otter_ai_core.stream.Stream`
    (iterated) and an outbound :class:`~otter_ai_core.stream.StreamWriter`
    (sent into).

    Single-consumer; not safe to iterate concurrently, like
    :class:`~otter_ai_core.stream.Stream`.
    """

    __slots__ = ("_inbound", "_outbound")

    def __init__(
        self, inbound: Stream[TEvent], outbound: StreamWriter[TClient]
    ) -> None:
        self._inbound = inbound
        self._outbound = outbound

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> TEvent:
        return await anext(self._inbound)

    def send(self, event: TClient) -> None:
        """Enqueue an outbound client event.

        No-op once :meth:`close` has run (delegates to
        :meth:`otter_ai_core.stream.StreamWriter.push`).
        """
        self._outbound.push(event)

    def close(self) -> None:
        """Signal that no more client events will be sent.

        Idempotent; sends after this are no-ops (delegates to
        :meth:`otter_ai_core.stream.StreamWriter.end`). The backend observes
        end-of-outbound and tears down its transport; the caller learns of
        completion when its inbound iteration stops.
        """
        self._outbound.end()


class ConnectionBackend[TClient, TEvent]:
    """Backend (transport-task) side of a bidirectional connection.

    The backend is the local producer's handle: it pushes inbound server
    events for the caller to iterate and drains the caller's outbound client
    events over ``async for``. It combines the producer face of an inbound
    :class:`~otter_ai_core.stream.StreamWriter` (``push`` / ``end``) with the
    consumer face of an outbound :class:`~otter_ai_core.stream.Stream`.

    The backend task should call :meth:`end` exactly once after its transport
    has torn down (or failed) — whether that teardown was triggered by the
    caller closing, the server closing, or an error.
    """

    __slots__ = ("_inbound", "_outbound")

    def __init__(
        self, inbound: StreamWriter[TEvent], outbound: Stream[TClient]
    ) -> None:
        self._inbound = inbound
        self._outbound = outbound

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> TClient:
        return await anext(self._outbound)

    def push(self, event: TEvent) -> None:
        """Push an inbound server event to the caller.

        No-op once :meth:`end` has run.
        """
        self._inbound.push(event)

    def end(self) -> None:
        """Signal end of the inbound stream. Idempotent.

        Pushes after this are no-ops. The caller's inbound iteration stops
        after this is called (and any already-enqueued events are drained).
        """
        self._inbound.end()


def create_connection[TClient, TEvent]() -> tuple[
    Connection[TClient, TEvent], ConnectionBackend[TClient, TEvent]
]:
    """Create a linked caller/backend pair sharing two queues.

    Returns the :class:`Connection` for the caller to iterate and send into,
    and the :class:`ConnectionBackend` for a transport-pump task to push
    inbound events into and drain outbound events from::

        conn, backend = create_connection()
        asyncio.create_task(_pump_transport(backend, ...))
        return conn
    """
    inbound_stream: Stream[TEvent]
    inbound_writer: StreamWriter[TEvent]
    inbound_stream, inbound_writer = create_stream()
    outbound_stream: Stream[TClient]
    outbound_writer: StreamWriter[TClient]
    outbound_stream, outbound_writer = create_stream()
    return (
        Connection(inbound_stream, outbound_writer),
        ConnectionBackend(inbound_writer, outbound_stream),
    )


#: Bidirectional peer of
#: :data:`~otter_ai_core.assistant_message_stream.AssistantMessageStreamFnBuilder`.
#:
#: A concrete value resolves provider config against whatever registries it
#: needs, opens a transport (e.g. a WebSocket for a realtime API), wires the
#: transport to the returned :class:`ConnectionBackend`, and returns the
#: :class:`Connection` synchronously — never raising, exactly like the stream
#: seam. The first argument is a provider-specific options bundle
#: (``TOptions``), the second a :class:`~otter_ai_core.context.Context`, and
#: the third an ``asyncio.Event`` cooperative-cancel signal.
#:
#: ``TClient`` and ``TEvent`` are the connection's outbound and inbound event
#: types. A typed specialisation fixes them (e.g. to ``ClientEvent`` /
#: ``ServerEvent`` in ``model_connection``); this generic alias is the
#: contract a provider package and a dispatch layer will agree on.
type ConnectionFn[TOptions, TClient, TEvent] = Callable[
    [TOptions, Context, asyncio.Event], Connection[TClient, TEvent]
]

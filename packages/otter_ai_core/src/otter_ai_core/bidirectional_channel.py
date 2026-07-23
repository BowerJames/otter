"""Generic async bidirectional-channel runtime.

A :class:`BidirectionalChannelClient` is the caller side of a bidirectional
conduit between a client and an async producer (the *backend*, typically a
transport-pump task): the client pushes outbound client events and iterates
inbound backend events, while the backend pushes inbound backend events and
drains outbound client events.

It is a thin composition of two
:func:`~otter_ai_core.channel.create_channel` push-queues, cross-wired one per
direction — there is no new queue or concurrency machinery here. A
unidirectional :class:`~otter_ai_core.channel.ChannelReader` pairs a reader
with a writer over a single queue; a bidirectional channel pairs a client
with a backend over **two** queues, one carrying backend→client events
(``TBackend``) and one carrying client→backend events (``TClient``).

The split mirrors :func:`~otter_ai_core.channel.create_channel`'s
reader/writer split, generalised to two directions. The client holds a
:class:`BidirectionalChannelClient` — it iterates inbound ``TBackend`` s and
pushes outbound ``TClient`` s. A transport-pump task holds the matching
:class:`BidirectionalChannelBackend` — it pushes inbound ``TBackend`` s and
drains outbound ``TClient`` s.

Why a primitive, not abortable
------------------------------
This module is the **queue primitive** for two directions: a thin composition
of two one-way channels, with no abort machinery of its own. Cooperative
abort belongs on the domain facade a consumer iterates, not on the primitive
— exactly as :mod:`otter_ai_core.channel` is an abort-free queue primitive and
:mod:`otter_ai_core.stream` layers the abortable facade over it. The
bidirectional peer of that facade is :mod:`otter_ai_core.connection`
(:class:`~otter_ai_core.connection.ConnectionClient` /
:class:`~otter_ai_core.connection.ConnectionBackend` over
:func:`create_bidirectional_channel`); not every bidirectional consumer needs
abort (the two directions of this primitive do not), so abort does not live
here.

Lifecycle
---------
The channel reuses :class:`~otter_ai_core.channel.ChannelWriter`'s ``None``
termination sentinel — there is no separate teardown handshake:

* **Client closes** — :meth:`BidirectionalChannelClient.end` ends the
  outbound writer. The backend's drain loop observes end-of-stream (the
  client has no more client events), tears down its transport, and calls
  :meth:`BidirectionalChannelBackend.end`, which ends the inbound writer.
  The client observes completion when its inbound iteration stops.
* **Server closes** — the backend detects transport EOF and calls
  :meth:`BidirectionalChannelBackend.end`; the client's inbound iteration
  stops.
* **Connect/transport failure** — the backend task, which owns the transport
  lifecycle (as a chat-completions producer owns its httpx client), encodes
  the failure however its typed event union allows, then ends the inbound
  writer. Because ``TBackend`` is generic, *core* cannot prescribe an
  error-event shape; a typed specialisation in a specialising package
  supplies it.

``end`` and ``push`` are synchronous (they enqueue / signal, matching
:class:`~otter_ai_core.channel.ChannelWriter.push` / ``.end``); the async
transport teardown is the backend task's concern. There is no ``aclose`` — a
client that wants to await full teardown drains its inbound channel to
completion after ending outbound.

Scope
-----
Otter defines **no transports, providers, API registry, or dispatch** here —
only the generic bidirectional runtime. **No producer-side seam type is
defined yet** (the former ``BidirectionalChannelFn`` was removed; a
connection-level seam will be added in a future dispatch package). A typed
``ConnectionClient[ClientEvent, ServerEvent]`` alias belongs in a
specialising subpackage, mirroring
:class:`~otter_ai_core.stream.StreamClient` (the abortable facade layered over
:class:`~otter_ai_core.channel.ChannelReader`). Like the
one-way channel runtime, :class:`BidirectionalChannelClient` and
:class:`BidirectionalChannelBackend` are runtime objects and are **not**
JSON-serializable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from otter_ai_core.channel import (
    ChannelPair,
    ChannelReader,
    ChannelWriter,
    create_channel,
)


class BidirectionalChannelClient[TClient, TBackend]:
    """Client side of a bidirectional channel.

    Iterate with ``async for event in channel`` to receive inbound backend
    events; call :meth:`push` to enqueue an outbound client event; call
    :meth:`end` to signal that no more client events will be sent. The
    channel is a thin facade over an inbound
    :class:`~otter_ai_core.channel.ChannelReader` (iterated) and an outbound
    :class:`~otter_ai_core.channel.ChannelWriter` (pushed into).

    Single-consumer; not safe to iterate concurrently, like
    :class:`~otter_ai_core.channel.ChannelReader`. Iterating honours the
    reader's single-pass guard: a second ``async for`` raises
    :class:`RuntimeError`.
    """

    __slots__ = ("_inbound", "_outbound")

    def __init__(self, inbound: ChannelReader[TBackend], outbound: ChannelWriter[TClient]) -> None:
        self._inbound = inbound
        self._outbound = outbound

    def __aiter__(self) -> Self:
        # Delegate to the inbound reader's ``__aiter__`` so its single-pass
        # guard fires on a second iteration (matching ``StreamClient``).
        self._inbound.__aiter__()
        return self

    async def __anext__(self) -> TBackend:
        return await anext(self._inbound)

    def push(self, event: TClient) -> None:
        """Enqueue an outbound client event.

        No-op once :meth:`end` has run (delegates to
        :meth:`otter_ai_core.channel.ChannelWriter.push`).
        """
        self._outbound.push(event)

    def end(self) -> None:
        """Signal that no more client events will be sent.

        Idempotent; pushes after this are no-ops (delegates to
        :meth:`otter_ai_core.channel.ChannelWriter.end`). The backend observes
        end-of-outbound and tears down its transport; the client learns of
        completion when its inbound iteration stops.
        """
        self._outbound.end()


class BidirectionalChannelBackend[TClient, TBackend]:
    """Backend (transport-task) side of a bidirectional channel.

    The backend is the local producer's handle: it pushes inbound backend
    events for the client to iterate and drains the client's outbound client
    events over ``async for``. It combines the producer face of an inbound
    :class:`~otter_ai_core.channel.ChannelWriter` (``push`` / ``end``) with the
    consumer face of an outbound :class:`~otter_ai_core.channel.ChannelReader`.

    The backend task should call :meth:`end` exactly once after its transport
    has torn down (or failed) — whether that teardown was triggered by the
    client ending outbound, the server closing, or an error.
    """

    __slots__ = ("_inbound", "_outbound")

    def __init__(self, inbound: ChannelWriter[TBackend], outbound: ChannelReader[TClient]) -> None:
        self._inbound = inbound
        self._outbound = outbound

    def __aiter__(self) -> Self:
        # Delegate to the outbound reader's ``__aiter__`` so its single-pass
        # guard fires on a second iteration (matching ``StreamClient``).
        self._outbound.__aiter__()
        return self

    async def __anext__(self) -> TClient:
        return await anext(self._outbound)

    def push(self, event: TBackend) -> None:
        """Push an inbound backend event to the client.

        No-op once :meth:`end` has run.
        """
        self._inbound.push(event)

    def end(self) -> None:
        """Signal end of the inbound channel. Idempotent.

        Pushes after this are no-ops. The client's inbound iteration stops
        after this is called (and any already-enqueued events are drained).
        """
        self._inbound.end()


@dataclass(slots=True, frozen=True)
class BidirectionalChannelPair[TClient, TBackend]:
    """A linked client/backend pair from :func:`create_bidirectional_channel`.

    ``client`` is the :class:`BidirectionalChannelClient` (the side iterated
    with ``async for`` and pushed into via :meth:`BidirectionalChannelClient.push`
    / :meth:`~BidirectionalChannelClient.end`); ``backend`` is the
    :class:`BidirectionalChannelBackend` (the side the transport-pump task
    pushes inbound events into and drains outbound events from). The two
    ends share two queues, one per direction. Frozen because a pair is an
    immutable binding of the two ends produced together.
    """

    client: BidirectionalChannelClient[TClient, TBackend]
    backend: BidirectionalChannelBackend[TClient, TBackend]


def create_bidirectional_channel[TClient, TBackend]() -> BidirectionalChannelPair[
    TClient, TBackend
]:
    """Create a linked client/backend pair sharing two queues.

    Returns a :class:`BidirectionalChannelPair` whose ``client`` is for the
    client to iterate and push into, and whose ``backend`` is for a
    transport-pump task to push inbound events into and drain outbound events
    from::

        pair = create_bidirectional_channel()
        asyncio.create_task(_pump_transport(pair.backend, ...))
        return pair.client
    """
    inbound: ChannelPair[TBackend] = create_channel()
    outbound: ChannelPair[TClient] = create_channel()
    return BidirectionalChannelPair(
        client=BidirectionalChannelClient(inbound.reader, outbound.writer),
        backend=BidirectionalChannelBackend(inbound.writer, outbound.reader),
    )

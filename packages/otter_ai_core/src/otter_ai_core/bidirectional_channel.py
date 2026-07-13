"""Generic async bidirectional-channel runtime.

A :class:`BidirectionalChannel` is a bidirectional conduit between a caller and
an async producer (the *backend*, typically a transport-pump task): the caller
sends outbound client events and iterates inbound server events, while the
backend pushes inbound server events and drains outbound client events.

It is a thin composition of two
:func:`~otter_ai_core.channel.create_channel` push-queues, cross-wired one per
direction — there is no new queue or concurrency machinery here. A
unidirectional :class:`~otter_ai_core.channel.ChannelReader` pairs a reader
with a writer over a single queue; a :class:`BidirectionalChannel` pairs a
caller with a backend over **two** queues, one carrying server→caller events
(``TEvent``) and one carrying caller→server events (``TClient``).

The split mirrors :func:`~otter_ai_core.channel.create_channel`'s
reader/writer split, generalised to two directions. The caller holds a
:class:`BidirectionalChannel` — it iterates inbound ``TEvent`` s and sends
outbound ``TClient`` s. A transport-pump task holds the matching
:class:`BidirectionalChannelBackend` — it pushes inbound ``TEvent`` s and
drains outbound ``TClient`` s.

Lifecycle
---------
The channel reuses :class:`~otter_ai_core.channel.ChannelWriter`'s ``None``
termination sentinel — there is no separate teardown handshake:

* **Caller closes** — :meth:`BidirectionalChannel.close` ends the outbound
  writer. The backend's drain loop observes end-of-stream (the caller has no
  more client events), tears down its transport, and calls
  :meth:`BidirectionalChannelBackend.end`, which ends the inbound writer. The
  caller observes completion when its inbound iteration stops.
* **Server closes** — the backend detects transport EOF and calls
  :meth:`BidirectionalChannelBackend.end`; the caller's inbound iteration
  stops.
* **Connect/transport failure** — the backend task, which owns the transport
  lifecycle (as the chat-completions producer owns its httpx client), encodes
  the failure however its typed event union allows, then ends the inbound
  writer. Because ``TEvent`` is generic, *core* cannot prescribe an
  error-event shape; a typed specialisation in a specialising package
  supplies it.

``close`` and ``send`` are synchronous (they enqueue / signal, matching
:class:`~otter_ai_core.channel.ChannelWriter.push` / ``.end``); the async
transport teardown is the backend task's concern. There is no ``aclose`` — a
caller that wants to await full teardown drains its inbound channel to
completion after closing.

Scope
-----
Otter defines **no transports, providers, API registry, or dispatch** here —
only the generic bidirectional runtime and the :data:`BidirectionalChannelFn`
seam type. A typed ``BidirectionalChannel[ClientEvent, ServerEvent]`` alias and
a typed seam alias belong in a specialising subpackage, mirroring how
:class:`~otter_ai_core.assistant_message_stream.AssistantMessageStream`
specialises :class:`~otter_ai_core.stream.StreamClient` (the abortable
facade layered over :class:`~otter_ai_core.channel.ChannelReader`). Like the
one-way channel runtime, :class:`BidirectionalChannel` and
:class:`BidirectionalChannelBackend` are runtime objects and are **not**
JSON-serializable.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Self

from otter_ai_core.channel import (
    ChannelPair,
    ChannelReader,
    ChannelWriter,
    create_channel,
)
from otter_ai_core.context import Context


class BidirectionalChannel[TClient, TEvent]:
    """Caller side of a bidirectional channel.

    Iterate with ``async for event in channel`` to receive inbound server
    events; call :meth:`send` to enqueue an outbound client event; call
    :meth:`close` to signal that no more client events will be sent. The
    channel is a thin facade over an inbound
    :class:`~otter_ai_core.channel.ChannelReader` (iterated) and an outbound
    :class:`~otter_ai_core.channel.ChannelWriter` (sent into).

    Single-consumer; not safe to iterate concurrently, like
    :class:`~otter_ai_core.channel.ChannelReader`.
    """

    __slots__ = ("_inbound", "_outbound")

    def __init__(
        self, inbound: ChannelReader[TEvent], outbound: ChannelWriter[TClient]
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
        :meth:`otter_ai_core.channel.ChannelWriter.push`).
        """
        self._outbound.push(event)

    def close(self) -> None:
        """Signal that no more client events will be sent.

        Idempotent; sends after this are no-ops (delegates to
        :meth:`otter_ai_core.channel.ChannelWriter.end`). The backend observes
        end-of-outbound and tears down its transport; the caller learns of
        completion when its inbound iteration stops.
        """
        self._outbound.end()


class BidirectionalChannelBackend[TClient, TEvent]:
    """Backend (transport-task) side of a bidirectional channel.

    The backend is the local producer's handle: it pushes inbound server
    events for the caller to iterate and drains the caller's outbound client
    events over ``async for``. It combines the producer face of an inbound
    :class:`~otter_ai_core.channel.ChannelWriter` (``push`` / ``end``) with the
    consumer face of an outbound :class:`~otter_ai_core.channel.ChannelReader`.

    The backend task should call :meth:`end` exactly once after its transport
    has torn down (or failed) — whether that teardown was triggered by the
    caller closing, the server closing, or an error.
    """

    __slots__ = ("_inbound", "_outbound")

    def __init__(
        self, inbound: ChannelWriter[TEvent], outbound: ChannelReader[TClient]
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
        """Signal end of the inbound channel. Idempotent.

        Pushes after this are no-ops. The caller's inbound iteration stops
        after this is called (and any already-enqueued events are drained).
        """
        self._inbound.end()


@dataclass(slots=True, frozen=True)
class BidirectionalChannelWiring[TClient, TEvent]:
    """A linked caller/backend pair from :func:`create_bidirectional_channel`.

    ``caller`` is the :class:`BidirectionalChannel` (the side iterated with
    ``async for`` and sent into via :meth:`BidirectionalChannel.send` /
    :meth:`~BidirectionalChannel.close`); ``backend`` is the
    :class:`BidirectionalChannelBackend` (the side the transport-pump task
    pushes inbound events into and drains outbound events from). The two
    ends share two queues, one per direction. Frozen because a wiring is an
    immutable binding of the two ends produced together.
    """

    caller: BidirectionalChannel[TClient, TEvent]
    backend: BidirectionalChannelBackend[TClient, TEvent]


def create_bidirectional_channel[TClient, TEvent]() -> BidirectionalChannelWiring[
    TClient, TEvent
]:
    """Create a linked caller/backend pair sharing two queues.

    Returns a :class:`BidirectionalChannelWiring` whose ``caller`` is for the
    caller to iterate and send into, and whose ``backend`` is for a
    transport-pump task to push inbound events into and drain outbound events
    from::

        wiring = create_bidirectional_channel()
        asyncio.create_task(_pump_transport(wiring.backend, ...))
        return wiring.caller
    """
    inbound: ChannelPair[TEvent] = create_channel()
    outbound: ChannelPair[TClient] = create_channel()
    return BidirectionalChannelWiring(
        caller=BidirectionalChannel(inbound.reader, outbound.writer),
        backend=BidirectionalChannelBackend(inbound.writer, outbound.reader),
    )


#: Bidirectional peer of
#: :data:`~otter_ai_core.assistant_message_stream.AssistantMessageStreamFnBuilder`.
#:
#: A concrete value resolves provider config against whatever registries it
#: needs, opens a transport (e.g. a WebSocket for a realtime API), wires the
#: transport to the returned :class:`BidirectionalChannelBackend`, and returns
#: the :class:`BidirectionalChannel` synchronously — never raising, exactly
#: like the one-way channel seam. The first argument is a provider-specific options
#: bundle (``TOptions``), the second a :class:`~otter_ai_core.context.Context`,
#: and the third an ``asyncio.Event`` cooperative-cancel signal.
#:
#: ``TClient`` and ``TEvent`` are the channel's outbound and inbound event
#: types. A typed specialisation fixes them (e.g. to a provider's client/server
#: event types in a specialising package); this generic alias is the
#: contract a provider package and a dispatch layer will agree on.
type BidirectionalChannelFn[TClient, TEvent] = Callable[
    [Context, asyncio.Event], BidirectionalChannel[TClient, TEvent]
]

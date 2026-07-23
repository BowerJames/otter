"""Generic abortable connection runtime layered over the bidirectional channel.

A :class:`ConnectionClient` / :class:`ConnectionBackend` pair is a
**bidirectional facade** over
:func:`~otter_ai_core.bidirectional_channel.create_bidirectional_channel`: a
consumer handle that can *iterate* inbound backend events **and** *push*
outbound client events **and** *abort*, paired with a producer handle that
*pushes* inbound events, *drains* outbound events, and *observes* the abort
signal — sharing two queues (via the bidirectional channel) and one
:class:`asyncio.Event` (the abort signal).

It is the bidirectional peer of :mod:`otter_ai_core.stream`: ``stream`` layers
an abortable one-way facade over :mod:`otter_ai_core.channel`; ``connection``
layers an abortable two-way facade over
:mod:`otter_ai_core.bidirectional_channel`. The layering is therefore:

* :mod:`otter_ai_core.channel` — the one-way queue primitive.
* :mod:`otter_ai_core.stream` — the abortable one-way facade over the channel.
* :mod:`otter_ai_core.bidirectional_channel` — the two-way queue primitive.
* :mod:`otter_ai_core.connection` — the abortable two-way facade (this module).
* :mod:`otter_ai_core.model_connection` — the typed two-way aliases.

Why a facade, not abort baked into the bidirectional channel
------------------------------------------------------------
The bidirectional channel is a pure two-queue primitive (two cross-wired
one-way channels). Not every bidirectional consumer needs abort, so
cancellation does not belong on the primitive — exactly as the one-way
:class:`~otter_ai_core.channel.ChannelReader` /
:class:`~otter_ai_core.channel.ChannelWriter` are abort-free and
:mod:`otter_ai_core.stream` layers the abortable facade over them. A
*connection* is the domain concept for "a bidirectional conduit a consumer can
cancel", composed of a bidirectional channel plus one shared abort event.

Abort is intrinsic, and also closes the outbound
-------------------------------------------------
The abort signal is **created with** the connection by
:func:`create_connection` and shared by both ends: the client sets it
(:meth:`ConnectionClient.abort`), the backend observes it
(:attr:`ConnectionBackend.abort_signal`). Unlike the one-way
:class:`~otter_ai_core.stream.StreamClient`, whose :meth:`~StreamClient.abort`
only sets the signal (the one-way consumer has nothing to close), a connection
client **also closes its outbound** when it aborts
(``abort()`` → set the signal **and** call :meth:`ConnectionClient.end`):
when the consumer aborts it is going away, so closing the outbound unblocks
the backend's drain loop and lets it tear down promptly. A producer that only
wants to observe the signal without closing outbound can call
:meth:`ConnectionClient.end` directly.

Symmetry with the one-way runtime
---------------------------------
The pair mirrors :class:`~otter_ai_core.stream.StreamClient` /
:class:`~otter_ai_core.stream.StreamBackend` / ``StreamPair`` /
:func:`~otter_ai_core.stream.create_stream`, generalised to two directions:
each end can both iterate **and** push. The product type mirrors
:class:`~otter_ai_core.bidirectional_channel.BidirectionalChannelPair`
(``ConnectionPair`` / :func:`create_connection`).

Scope
-----
Otter defines **no transports, providers, API registry, or dispatch** here —
only the generic abortable connection runtime. **No producer-side seam type
is defined yet** (a connection-level seam will be added in a future dispatch
package). Like the bidirectional channel runtime,
:class:`ConnectionClient` and :class:`ConnectionBackend` are runtime objects
and are **not** JSON-serializable; the serializable data model is unchanged.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Self

from otter_ai_core.bidirectional_channel import (
    BidirectionalChannelBackend,
    BidirectionalChannelClient,
    BidirectionalChannelPair,
    create_bidirectional_channel,
)


class ConnectionClient[TClient, TBackend]:
    """Client end of a connection: iterate inbound, push outbound, **and** abort.

    Iterate with ``async for event in client:`` to receive inbound backend
    events; call :meth:`push` to enqueue an outbound client event; call
    :meth:`end` to signal that no more client events will be sent; call
    :meth:`abort` to cooperatively cancel the producer **and** close the
    outbound. A thin facade over a
    :class:`~otter_ai_core.bidirectional_channel.BidirectionalChannelClient`.

    Single-consumer on the inbound side; iterating honours the underlying
    reader's single-pass guard (a second ``async for`` raises
    :class:`RuntimeError`).
    """

    __slots__ = ("_client", "_abort_signal")

    def __init__(
        self,
        client: BidirectionalChannelClient[TClient, TBackend],
        abort_signal: asyncio.Event,
    ) -> None:
        self._client = client
        self._abort_signal = abort_signal

    def abort(self) -> None:
        """Signal the producer to abort **and** close the outbound. Idempotent.

        Sets the shared abort :class:`asyncio.Event` (observed by the paired
        :class:`ConnectionBackend` via :attr:`ConnectionBackend.abort_signal`)
        and calls :meth:`end` so the backend's outbound drain unblocks. This
        is intentionally stronger than
        :meth:`~otter_ai_core.stream.StreamClient.abort` (which only sets the
        signal): a bidirectional consumer that aborts is going away, so its
        outbound must be closed to let the backend tear down promptly.
        """
        self._abort_signal.set()
        self.end()

    def push(self, event: TClient) -> None:
        """Enqueue an outbound client event. No-op once :meth:`end` has run."""
        self._client.push(event)

    def end(self) -> None:
        """Signal that no more client events will be sent. Idempotent.

        Pushes after this are no-ops. The backend observes end-of-outbound;
        the client learns of full completion when its inbound iteration stops.
        """
        self._client.end()

    def __aiter__(self) -> Self:
        # Delegate to the underlying client's ``__aiter__`` so the inbound
        # reader's single-pass guard fires on a second iteration (matching
        # ``StreamClient``).
        self._client.__aiter__()
        return self

    async def __anext__(self) -> TBackend:
        return await anext(self._client)


class ConnectionBackend[TClient, TBackend]:
    """Backend end of a connection: push inbound, drain outbound, observe abort.

    A thin facade over a
    :class:`~otter_ai_core.bidirectional_channel.BidirectionalChannelBackend`
    (:meth:`push` / :meth:`end` / iteration delegate to it) plus the shared
    abort signal (:attr:`abort_signal`).

    The producer should poll ``abort_signal.is_set()`` between units of work
    and ``await abort_signal.wait()`` in any long-lived wait, terminating its
    transport and calling :meth:`end` when it fires. Because the client's
    :meth:`ConnectionClient.abort` also closes the outbound, a backend draining
    outbound events over ``async for`` will observe end-of-outbound on abort.
    """

    __slots__ = ("_backend", "_abort_signal")

    def __init__(
        self,
        backend: BidirectionalChannelBackend[TClient, TBackend],
        abort_signal: asyncio.Event,
    ) -> None:
        self._backend = backend
        self._abort_signal = abort_signal

    @property
    def abort_signal(self) -> asyncio.Event:
        """The cooperative-abort signal shared with the :class:`ConnectionClient`.

        Observe it with ``await backend.abort_signal.wait()`` /
        ``backend.abort_signal.is_set()``.
        """
        return self._abort_signal

    def push(self, event: TBackend) -> None:
        """Push an inbound backend event to the client.

        No-op once :meth:`end` has run.
        """
        self._backend.push(event)

    def end(self) -> None:
        """Signal end of the inbound channel. Idempotent; pushes after are no-ops."""
        self._backend.end()

    def __aiter__(self) -> Self:
        # Delegate to the underlying backend's ``__aiter__`` so the outbound
        # reader's single-pass guard fires on a second iteration.
        self._backend.__aiter__()
        return self

    async def __anext__(self) -> TClient:
        return await anext(self._backend)


@dataclass(slots=True, frozen=True)
class ConnectionPair[TClient, TBackend]:
    """A linked client/backend pair from :func:`create_connection`.

    ``client`` is the :class:`ConnectionClient` (the side iterated for inbound
    events, pushed into for outbound events, and aborted via
    :meth:`ConnectionClient.abort`); ``backend`` is the :class:`ConnectionBackend`
    (the side the producer task pushes inbound events into, drains outbound
    events from, and reads the abort signal from). The two ends share two
    queues (via the bidirectional channel) and one abort
    :class:`asyncio.Event`. Frozen because a pair is an immutable binding of
    the two ends produced together.
    """

    client: ConnectionClient[TClient, TBackend]
    backend: ConnectionBackend[TClient, TBackend]


def create_connection[TClient, TBackend]() -> ConnectionPair[TClient, TBackend]:
    """Create a linked client/backend pair sharing two queues and one abort signal.

    A producer task keeps the :class:`ConnectionBackend` (pushing inbound
    events, draining outbound events, observing
    :attr:`ConnectionBackend.abort_signal`) and returns the
    :class:`ConnectionClient` (iterated, pushed into, and aborted by the
    consumer)::

        pair = create_connection()
        asyncio.create_task(_pump_transport(pair.backend, ...))
        return pair.client

    The abort signal is intrinsic to the connection — the consumer signals via
    :meth:`ConnectionClient.abort` (which also closes the outbound) and the
    producer observes :attr:`ConnectionBackend.abort_signal`. No abort argument
    is threaded through the producer's seam.
    """
    channel: BidirectionalChannelPair[TClient, TBackend] = create_bidirectional_channel()
    abort_signal: asyncio.Event = asyncio.Event()
    return ConnectionPair(
        client=ConnectionClient(channel.client, abort_signal),
        backend=ConnectionBackend(channel.backend, abort_signal),
    )

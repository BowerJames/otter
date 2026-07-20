from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Self

from otter_ai_core.channel import (
    ChannelPair,
    ChannelReader,
    ChannelWriter,
    create_channel,
)


class StreamClient[TEvent]:
    """Consumer interface to a stream: iterate **and** abort.

    Iterate with ``async for event in client:`` or drive it directly with
    ``await anext(client)`` (the connection adapter uses the latter); both
    delegate to the underlying :class:`~otter_ai_core.channel.ChannelReader`,
    whose single-pass guard still fires (a second ``async for`` raises
    :class:`RuntimeError`). Call :meth:`abort` to signal the producer to stop.

    Single-consumer / single-pass, like
    :class:`~otter_ai_core.channel.ChannelReader`: a second ``async for``
    (even after the first finished) raises :class:`RuntimeError`, because the
    guard lives on the shared reader.
    """

    __slots__ = ("_reader", "_abort_signal")

    def __init__(self, reader: ChannelReader[TEvent], abort_signal: asyncio.Event) -> None:
        self._reader = reader
        self._abort_signal = abort_signal

    def abort(self) -> None:
        """Signal the producer to abort. Idempotent.

        Sets the shared abort :class:`asyncio.Event`; the paired
        :class:`StreamBackend` observes it via :attr:`StreamBackend.abort_signal`.
        """
        self._abort_signal.set()

    def __aiter__(self) -> Self:
        # Serve as our own async iterator so both ``async for`` and direct
        # ``anext()`` are supported (the connection adapter drives streams with
        # ``anext()`` directly, not ``async for``). Triggering the reader's
        # ``__aiter__`` honours its single-pass guard: a second ``async for``
        # raises :class:`RuntimeError`.
        self._reader.__aiter__()
        return self

    async def __anext__(self) -> TEvent:
        return await anext(self._reader)


class StreamBackend[TEvent]:
    """Producer interface to a stream: push events, end, and observe abort.

    A thin facade over a :class:`~otter_ai_core.channel.ChannelWriter`
    (:meth:`push` / :meth:`end` delegate to it) plus the shared abort signal
    (:attr:`abort_signal`). Mirrors
    :class:`~otter_ai_core.bidirectional_channel.BidirectionalChannelBackend`,
    which folds its inbound :class:`~otter_ai_core.channel.ChannelWriter` into
    ``push`` / ``end`` methods.

    The producer should poll ``abort_signal.is_set()`` between units of work
    and ``await abort_signal.wait()`` in any long-lived wait, terminating the
    stream with an aborted terminal event when it fires.
    """

    __slots__ = ("_writer", "_abort_signal")

    def __init__(self, writer: ChannelWriter[TEvent], abort_signal: asyncio.Event) -> None:
        self._writer = writer
        self._abort_signal = abort_signal

    @property
    def abort_signal(self) -> asyncio.Event:
        """The cooperative-abort signal shared with the :class:`StreamClient`.

        Observe it with ``await backend.abort_signal.wait()`` /
        ``backend.abort_signal.is_set()``.
        """
        return self._abort_signal

    def push(self, event: TEvent) -> None:
        """Enqueue an event. No-op once :meth:`end` has run."""
        self._writer.push(event)

    def end(self) -> None:
        """Signal end-of-stream. Idempotent; pushes after this are no-ops."""
        self._writer.end()


@dataclass(slots=True, frozen=True)
class StreamPair[TEvent]:
    """A linked client/backend pair from :func:`create_stream`.

    ``client`` is the :class:`StreamClient` (the side iterated with
    ``async for`` and aborted via :meth:`StreamClient.abort`); ``backend`` is
    the :class:`StreamBackend` (the side the producer task pushes into and
    reads the abort signal from). The two ends share one queue (via the
    channel) and one abort :class:`asyncio.Event`. Frozen because a pair is an
    immutable binding of the two ends produced together.
    """

    client: StreamClient[TEvent]
    backend: StreamBackend[TEvent]


def create_stream_pair[TEvent]() -> StreamPair[TEvent]:
    """Create a linked client/backend pair sharing one queue and one abort signal.

    A producer task keeps the :class:`StreamBackend` (pushing events, observing
    :attr:`StreamBackend.abort_signal`) and returns the :class:`StreamClient`
    (iterated and aborted by the consumer)::

        pair = create_stream()
        asyncio.create_task(_produce(pair.backend, ...))
        return pair.client

    The abort signal is intrinsic to the stream — the consumer signals via
    :meth:`StreamClient.abort` and the producer observes
    :attr:`StreamBackend.abort_signal`. No abort argument is threaded through
    the producer's seam.
    """
    channel: ChannelPair[TEvent] = create_channel()
    abort_signal: asyncio.Event = asyncio.Event()
    return StreamPair(
        client=StreamClient(channel.reader, abort_signal),
        backend=StreamBackend(channel.writer, abort_signal),
    )

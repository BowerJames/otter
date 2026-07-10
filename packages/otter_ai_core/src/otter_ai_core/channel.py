"""Generic async channel runtime and typed message-stream aliases.

A faithful Python/``asyncio`` port of the ``EventStream`` push-queue from
``@earendil-works/pi-ai``. This module provides the *runtime* — an async
single-consumer queue split into a read end (:class:`ChannelReader`) and a
write end (:class:`ChannelWriter`). The typed message-stream aliases live in
:mod:`otter_ai_core.assistant_message_stream`.

Why "channel"
--------------
The runtime is a single-consumer queue **split into two handles distributed to
two concurrent tasks**: a producer task holds the :class:`ChannelWriter` (the
write end) and a consumer task iterates the :class:`ChannelReader` (the read
end). That split-and-distribute topology is the essence of a *channel* —
structurally identical to ``tokio::sync::mpsc::channel() -> (Sender, Receiver)``,
right down to the sender closing to signal completion. A "stream", by contrast,
is usually a single iterable object one actor pulls from; and in Python
``asyncio.StreamReader``/``StreamWriter`` read *bytes* off a transport, a
connotation that does not fit a typed-event conduit. (The *values* flowing
through a channel — an LLM response — are genuinely a stream; the typed
:data:`~otter_ai_core.assistant_message_stream.AssistantMessageStream` alias
keeps that domain vocabulary, and just specializes this channel's read end.)

Writer contract (matches pi-ai)
-------------------------------
A producer pushes every event, **including** the terminal ``done``/``error``
event, then calls :meth:`ChannelWriter.end`. The consumer sees each event via
``async for`` (the terminal event is yielded *before* iteration stops, so the
final message is always reachable), after which iteration ends. Cooperative
abort is the producer's concern (via its own ``asyncio`` task / signal), as in
pi-ai.

Why no ``result()``
-------------------
pi-ai's ``EventStream.result()`` is sugar that drains the stream and returns
the terminal event's message. :class:`ChannelReader` deliberately stays a
single-param ``ChannelReader[TEvent]`` iterator so the runtime is symmetric and
generic; consumers read the terminal ``done``/``error`` event directly. (A
provider package may add a ``complete_assistant`` helper later without baking
it into the core type.)

Scope
-----
Otter defines **no providers, no API registry, and no ``stream()`` dispatch** —
only this generic runtime. :class:`ChannelReader` and :class:`ChannelWriter`
are runtime objects and are **not** JSON-serializable (unlike
:class:`~otter_ai_core.context.Context`); the serializable data model is
unchanged.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Self


class _Core[TEvent]:
    """Shared queue state linking a channel's read end to its write end.

    ``None`` is the termination sentinel pushed by :meth:`ChannelWriter.end`;
    it is safe because events are never ``None``.
    """

    __slots__ = ("queue", "done")

    def __init__(self) -> None:
        self.queue: asyncio.Queue[TEvent | None] = asyncio.Queue()
        self.done: bool = False


class ChannelReader[TEvent]:
    """Read end of a channel: a single-pass ``AsyncIterator`` of events.

    Iterate with ``async for event in channel:``. Iteration ends after the
    writer's :meth:`ChannelWriter.end` (the terminal ``done``/``error`` event
    is yielded *before* iteration stops, so the final message is always
    reachable).

    Single-consumer / single-pass: the read end may be iterated **at most
    once**. A second ``async for`` (even after the first finished) raises
    :class:`RuntimeError`. The guard lives in ``__aiter__`` — which is
    **synchronous** because ``async for`` does not await ``__aiter__``; the
    check-then-set is race-free under the single-threaded asyncio loop.
    """

    __slots__ = ("_core", "_iterating")

    def __init__(self, core: _Core[TEvent]) -> None:
        self._core = core
        self._iterating = False

    def __aiter__(self) -> Self:
        if self._iterating:
            raise RuntimeError(
                "ChannelReader is single-consumer and single-pass: already iterated"
            )
        self._iterating = True
        return self

    async def __anext__(self) -> TEvent:
        item = await self._core.queue.get()
        if item is None:
            raise StopAsyncIteration
        return item


class ChannelWriter[TEvent]:
    """Write end of a channel.

    Push every event (including the terminal ``done``/``error``), then call
    :meth:`end`. Both methods are idempotent no-ops once :meth:`end` has run.
    """

    __slots__ = ("_core",)

    def __init__(self, core: _Core[TEvent]) -> None:
        self._core = core

    def push(self, event: TEvent) -> None:
        """Enqueue an event.

        No-op once :meth:`end` has run.
        """
        if self._core.done:
            return
        self._core.queue.put_nowait(event)

    def end(self) -> None:
        """Signal end-of-stream. Idempotent; pushes after this are no-ops."""
        if self._core.done:
            return
        self._core.done = True
        self._core.queue.put_nowait(None)


@dataclass(slots=True, frozen=True)
class ChannelPair[TEvent]:
    """A linked read/write pair from :func:`create_channel`.

    ``writer`` is the :class:`ChannelWriter` (the write end, that
    ``push``/``end``); ``reader`` is the :class:`ChannelReader` (the read end,
    iterated with ``async for``). The two ends share one queue. Frozen because
    a pair is an immutable binding of the two ends produced together.
    """

    writer: ChannelWriter[TEvent]
    reader: ChannelReader[TEvent]


def create_channel[TEvent]() -> ChannelPair[TEvent]:
    """Create a linked read/write pair sharing one queue.

    A producer keeps the :class:`ChannelWriter` (the write end) and returns the
    :class:`ChannelReader` (the read end) to its caller::

        wiring = create_channel()
        asyncio.create_task(_run(wiring.writer, ...))
        return wiring.reader
    """
    core = _Core[TEvent]()
    return ChannelPair(
        writer=ChannelWriter[TEvent](core),
        reader=ChannelReader[TEvent](core),
    )

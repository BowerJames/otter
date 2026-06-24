"""Generic async stream runtime and typed message-stream aliases.

A faithful Python/``asyncio`` port of the ``EventStream`` push-queue from
``@earendil-works/pi-ai``. This module provides the *runtime* — an async
single-consumer queue split into a consumer :class:`Stream` and a producer
:class:`StreamWriter` — plus the typed stream aliases a provider package built
on top will import.

Producer contract (matches pi-ai)
---------------------------------
A producer pushes every event, **including** the terminal ``done``/``error``
event, then calls :meth:`StreamWriter.end`. The consumer sees each event via
``async for`` (the terminal event is yielded *before* iteration stops, so the
final message is always reachable), after which iteration ends. Cooperative
abort is the producer's concern (via its own ``asyncio`` task / signal), as in
pi-ai.

Why no ``result()``
-------------------
pi-ai's ``EventStream.result()`` is sugar that drains the stream and returns
the terminal event's message. :class:`Stream` deliberately stays a
single-param ``Stream[TEvent]`` iterator so the runtime is symmetric and
generic; consumers read the terminal ``done``/``error`` event directly. (A
provider package may add a ``complete_assistant`` helper later without baking
it into the core type.)

Scope
-----
Otter defines **no providers, no API registry, and no ``stream()`` dispatch** —
only this generic runtime and the types that specialize it. :class:`Stream`
and :class:`StreamWriter` are runtime objects and are **not** JSON-serializable
(unlike :class:`~otter_ai_core.context.Context`); the serializable data model is
unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Self

from otter_ai_core.assistant_message_events import (
    AssistantMessageEvent,
)
from otter_ai_core.context import Context


class _Core[TEvent]:
    """Shared queue state linking a :class:`Stream` to its :class:`StreamWriter`.

    ``None`` is the termination sentinel pushed by :meth:`StreamWriter.end` /
    :meth:`Stream.aclose`; it is safe because events are never ``None``.
    """

    __slots__ = ("queue", "done")

    def __init__(self) -> None:
        self.queue: asyncio.Queue[TEvent | None] = asyncio.Queue()
        self.done: bool = False


class Stream[TEvent]:
    """Consumer side of a stream: a single-pass ``AsyncIterator`` of events.

    Iterate with ``async for event in stream:``. Iteration ends after the
    producer's :meth:`StreamWriter.end` (the terminal ``done``/``error`` event
    is yielded *before* iteration stops, so the final message is always
    reachable). Single-consumer; not safe to iterate concurrently.
    """

    __slots__ = ("_core",)

    def __init__(self, core: _Core[TEvent]) -> None:
        self._core = core

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> TEvent:
        item = await self._core.queue.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def aclose(self) -> None:
        """Mark the stream done and unblock any pending consumer ``await``.

        Idempotent. Any events still queued after this point are discarded by
        the consumer (iteration stops at the sentinel). The producer's
        subsequent :meth:`StreamWriter.push` calls become no-ops.
        """
        if self._core.done:
            return
        self._core.done = True
        self._core.queue.put_nowait(None)


class StreamWriter[TEvent]:
    """Producer side of a stream.

    Push every event (including the terminal ``done``/``error``), then call
    :meth:`end`. Both methods are idempotent no-ops once :meth:`end` has run.
    """

    __slots__ = ("_core",)

    def __init__(self, core: _Core[TEvent]) -> None:
        self._core = core

    def push(self, event: TEvent) -> None:
        """Enqueue an event.

        No-op once :meth:`end` (or :meth:`Stream.aclose`) has run.
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


def create_stream[TEvent]() -> tuple[Stream[TEvent], StreamWriter[TEvent]]:
    """Create a linked consumer/producer pair sharing one queue.

    A provider's ``stream()``-style function keeps the :class:`StreamWriter`
    and returns the :class:`Stream` to its caller::

        consumer, writer = create_stream()
        asyncio.create_task(_run(writer, ...))
        return consumer
    """
    core = _Core[TEvent]()
    return Stream[TEvent](core), StreamWriter[TEvent](core)


# --------------------------------------------------------------------------- #
# Typed aliases
# --------------------------------------------------------------------------- #
#
# Plain assignment (not PEP 695 ``type`` statements). ``TEvent`` is invariant
# because ``StreamWriter.push`` accepts it, so covariance is not available
# regardless.

#: Stream of assistant streaming events (single assistant message per stream).
AssistantMessageStream = Stream[AssistantMessageEvent]

#: Producer handle for an :data:`AssistantMessageStream`.
AssistantMessageWriter = StreamWriter[AssistantMessageEvent]

#: Function that builds an :data:`AssistantMessageStream`.
#:
#: Producer-side seam between a provider package and a future dispatch layer
#: (mirrors ``StreamFunction`` in @earendil-works/pi-ai, with the model and
#: options slots collapsed into one: ``TOptions``).
#:
#: The first argument carries the provider's per-call configuration. A future
#: dispatch layer would key on the model's ``api`` (read off the configuration)
#: and invoke the registered function with ``(options, context)``. Otter
#: defines no dispatch today — this alias is the contract a provider package
#: and a dispatch layer will agree on.
#:
#: ``TOptions`` is open because the realistic shape is a provider-specific
#: **options bundle** — pure-data config (model id, temperature, max tokens,
#: API key, …) bundled with runtime handles (hooks, abort signals) that cannot
#: travel out-of-band (a closure is per-call and defeats registry-keyed lookup;
#: registry metadata is per-registration, not per-call). A provider that needs
#: nothing beyond the model may specialize ``TOptions`` to a bare ``Model``
#: type, but the options-bundle form is the intended pattern.
type AssistantMessageStreamFn[TOptions] = Callable[
    [TOptions, Context], AssistantMessageStream
]

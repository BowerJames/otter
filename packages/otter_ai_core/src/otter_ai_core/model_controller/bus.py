"""A typed pub/sub bus for server→client model-connection events.

A :class:`ModelBus` fans each :data:`~otter_ai_core.model_connection.ServerContextEvent`
out to the async handlers subscribed to its ``type``. It is a small,
self-contained entity with its own writer/reader channel and its own worker
task: :meth:`publish` enqueues an event (synchronous, non-blocking) and the
worker task drains the queue, awaiting each subscribed handler in subscription
order.

Handler isolation
-----------------
A raising handler is **isolated**: the worker catches :class:`Exception` (not
``BaseException``, so :class:`~asyncio.CancelledError` still propagates and
shuts the bus down), logs it at ``ERROR`` via the stdlib idiom
``logging.getLogger(__name__)`` (which routes to stderr once the application
has configured :mod:`otter_ai_logging`), and continues to the next handler /
event. One misbehaving subscriber therefore cannot poison the bus for other
subscribers or stall the controller's event flow.

Lifecycle
---------
:meth:`end` closes the bus's writer; the worker drains any already-published
events (handlers still fire for them) and then exits. :meth:`aclose` ends the
writer and awaits the worker's completion with a deadline — if a handler hangs
so the drain never finishes, the worker is force-cancelled so no owned task is
left pending (the deterministic last resort, in place of relying on GC).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from otter_ai_core.channel import ChannelPair, create_channel
from otter_ai_core.model_connection import ServerContextEvent, ServerContextEventType

#: Default graceful-drain deadline (seconds) for :meth:`ModelBus.aclose`.
#: ``None`` would wait forever; a finite default keeps teardown deterministic
#: when a handler wedges.
_DEFAULT_ACLOSE_TIMEOUT: float = 5.0

#: An async subscriber invoked for each matching server event.
Handler = Callable[[ServerContextEvent], Awaitable[None]]

_log = logging.getLogger(__name__)


class ModelBus:
    """A pub/sub bus keyed on :class:`ServerContextEventType`.

    Subscribe with :meth:`subscribe` (returns an idempotent unsubscribe
    callable), publish with :meth:`publish`. Handlers are awaited sequentially
    per event in subscription order; a raising handler is logged and skipped
    (see the module docstring). End with :meth:`end` (fire-and-forget) or
    :meth:`aclose` (awaited, deadline-bounded).
    """

    __slots__ = ("_reader", "_writer", "_handlers", "_task")

    def __init__(self) -> None:
        channel_pair: ChannelPair[ServerContextEvent] = create_channel()
        self._reader = channel_pair.reader
        self._writer = channel_pair.writer
        self._handlers: dict[ServerContextEventType, list[Handler]] = {
            event_type: [] for event_type in ServerContextEventType
        }
        self._task: asyncio.Task[None] = asyncio.create_task(self._run())

    async def _run(self) -> None:
        async for event in self._reader:
            for handler in self._handlers[event.type]:
                try:
                    await handler(event)
                except Exception:
                    # Isolate the subscriber: log and keep dispatching. Do not
                    # catch BaseException — CancelledError must propagate so the
                    # worker can be torn down on aclose().
                    _log.error(
                        "model bus handler raised for %r; continuing",
                        event.type,
                        exc_info=True,
                    )

    def subscribe(
        self, event_type: ServerContextEventType, handler: Handler
    ) -> Callable[[], None]:
        """Register ``handler`` for ``event_type``; return an unsubscribe callable.

        The returned callable removes the handler and is idempotent — calling
        it more than once is a no-op after the first.
        """
        self._handlers[event_type].append(handler)
        removed = False

        def _unsubscribe() -> None:
            nonlocal removed
            if removed:
                return
            removed = True
            with contextlib.suppress(ValueError):  # already gone / never added
                self._handlers[event_type].remove(handler)

        return _unsubscribe

    def publish(self, event: ServerContextEvent) -> None:
        """Enqueue an event for the worker to fan out to its handlers."""
        self._writer.push(event)

    def end(self) -> None:
        """Signal that no more events will be published.

        The worker still drains already-published events (handlers fire for
        them) and then exits. Idempotent (delegates to the channel writer).
        """
        self._writer.end()

    async def aclose(self, timeout: float | None = _DEFAULT_ACLOSE_TIMEOUT) -> None:
        """End the writer and await the worker's drain to completion.

        Lets already-published events reach their handlers, then awaits the
        worker task. ``timeout`` bounds the graceful drain (``None`` waits
        forever — drain-or-hang); if it overruns, the worker is force-cancelled
        so no owned task is left pending. Safe to call more than once.
        """
        self.end()
        if self._task.done():
            return
        try:
            await asyncio.wait_for(self._task, timeout)
        except TimeoutError:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        except BaseException:
            # aclose() itself was cancelled: cancel the worker too, then re-raise.
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            raise

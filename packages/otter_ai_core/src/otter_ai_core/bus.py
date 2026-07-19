"""Generic typed asynchronous event bus.

A :class:`Bus` fans events out to async handlers subscribed to their ``type``
discriminator. The complete event family is a type parameter, so handlers keep
discriminated-union narrowing rather than receiving only a generic base model.
Events need not inherit from a particular class or use Pydantic; they only need
to satisfy :class:`~otter_ai_core.event.EventLike` structurally.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum

from otter_ai_core.channel import ChannelPair, create_channel
from otter_ai_core.event import EventLike

_logger = logging.getLogger(__name__)

_DEFAULT_ACLOSE_TIMEOUT: float = 5.0


type BusHandler[TEvent] = Callable[[TEvent], Awaitable[None]]


async def _await_or_cancel(task: asyncio.Task[None], timeout: float | None) -> None:
    """Await ``task`` for up to ``timeout`` seconds; force-cancel if it overruns.

    ``timeout`` of ``None`` waits indefinitely (drain-or-hang). A timed-out or
    otherwise-interrupted await still cancels the task (so its ``finally`` blocks
    run) so no owned task is left pending. No-op if ``task`` is already done.
    """
    if task.done():
        return
    try:
        await asyncio.wait_for(task, timeout)
    except TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    except BaseException:
        # The await itself was cancelled: cancel the task too, then re-raise.
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        raise


class Bus[TType: StrEnum, TEvent: EventLike]:
    """A pub/sub bus for a structurally typed discriminated event family.

    ``TEvent`` should be the complete event union. This lets a handler match on
    ``event.type`` and narrow to a concrete variant. Python cannot statically
    express that ``TEvent.type`` belongs specifically to ``TType``, so
    :meth:`publish` validates that relationship before enqueueing and the
    worker checks it defensively again before dispatch.

    The constructor schedules a background worker task and must therefore be
    called from within a running :mod:`asyncio` event loop.
    """

    __slots__ = ("_event_type", "_reader", "_writer", "_handlers", "_task")

    def __init__(self, event_type: type[TType]) -> None:
        self._event_type = event_type
        channel_pair: ChannelPair[tuple[TType, TEvent]] = create_channel()
        self._reader = channel_pair.reader
        self._writer = channel_pair.writer
        self._handlers: dict[TType, list[BusHandler[TEvent]]] = {
            member: [] for member in self.event_type
        }
        self._task: asyncio.Task[None] = asyncio.create_task(self._run())

    @property
    def event_type(self) -> type[TType]:
        return self._event_type

    async def _run(self) -> None:
        async for published_type, event in self._reader:
            event_type = event.type
            if not isinstance(event_type, self._event_type) or event_type is not published_type:
                # publish() validates and snapshots the discriminator before
                # enqueueing. Do not let an event mutated while queued poison
                # the worker or dispatch to handlers for another variant.
                _logger.error(
                    "bus dropped event whose discriminator changed from %r to %r",
                    published_type,
                    event_type,
                )
                continue

            for handler in self._handlers[published_type]:
                try:
                    await handler(event)
                except Exception:
                    # Isolate the subscriber: log and keep dispatching. Do not
                    # catch BaseException — CancelledError must propagate so the
                    # worker can be torn down on aclose().
                    _logger.error(
                        "bus handler raised for %r; continuing",
                        published_type,
                        exc_info=True,
                    )

    def subscribe(self, event_type: TType, handler: BusHandler[TEvent]) -> Callable[[], None]:
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

    def publish(self, event: TEvent) -> None:
        """Validate and enqueue an event for the worker to fan out.

        Raises:
            RuntimeError: If ``event.type`` does not belong to this bus's
                discriminator enum.
        """
        event_type = event.type
        if not isinstance(event_type, self._event_type):
            raise RuntimeError(
                f"event discriminator {event_type!r} does not belong to {self._event_type.__name__}"
            )
        self._writer.push((event_type, event))

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
        await _await_or_cancel(self._task, timeout)

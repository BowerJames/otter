"""Fan-out event bus for the model session.

A single :class:`ModelSessionBus` is owned by a
:class:`~otter_ai_core.model_session.ModelSession`. The inbound pump publishes
reduced :data:`~otter_ai_core.model_session.events.SessionEvent` s via
:meth:`publish`; subscribers register typed handlers via :meth:`subscribe` and
are awaited serially in registration order (one slow handler stalls the next
event — a known v1 tradeoff, fine for text, to revisit when audio lands).

The bus is transport-agnostic: it knows nothing about
:data:`~otter_ai_core.model_connection.ServerEvent`. The reduction from wire to
bus events happens in the session's inbound pump via
:mod:`~otter_ai_core.model_session.reduce`.

Handler failures are contained: a handler that raises has its exception
captured and re-emitted as a
:class:`~otter_ai_core.model_session.events.HandlerErrorEvent` so one bad
handler cannot kill the bus for everyone else. Error events do not emit error
events (recursion cap — see the event's docstring).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from otter_ai_core.hook import Hook

from .events import (
    HandlerErrorEvent,
    SessionEvent,
    SessionEventTypes,
)


class ModelSessionBus:
    _queue: asyncio.Queue[SessionEvent]
    _running: bool
    _task: asyncio.Task[None]
    _handlers: dict[SessionEventTypes, list[Hook[SessionEvent, None]]]

    def __init__(self) -> None:
        self._queue = asyncio.Queue[SessionEvent]()
        self._handlers = {value: [] for value in SessionEventTypes}
        self._running = True
        self._task = asyncio.create_task(self._run())

    def publish(self, event: SessionEvent | None) -> None:
        match event:
            case None:
                self._running = False
            case _:
                self._queue.put_nowait(event)

    def subscribe(
        self,
        event: SessionEventTypes,
        handler: Hook[SessionEvent, None],
    ) -> Callable[[], None]:
        self._handlers[event].append(handler)
        return lambda: self._unsubscribe(event, handler)

    def _unsubscribe(
        self,
        event: SessionEventTypes,
        handler: Hook[SessionEvent, None],
    ) -> None:
        self._handlers[event].remove(handler)

    async def _run(self) -> None:
        while self._running:
            event = await self._queue.get()
            await self._handle(event)
        while not self._queue.empty():
            event = self._queue.get_nowait()
            await self._handle(event)

    async def _handle(self, event: SessionEvent) -> None:
        for handler in self._handlers[event.type]:
            try:
                await handler(event)
            except Exception as exc:
                # Error events do not emit error events — a handler raising
                # while handling a HandlerErrorEvent is swallowed silently,
                # capping recursion at one level so a buggy error-handler
                # cannot feed the queue forever.
                if isinstance(event, HandlerErrorEvent):
                    continue
                self.publish(
                    HandlerErrorEvent(
                        type=SessionEventTypes.HandlerError,
                        event_type=event.type,
                        handler_name=_handler_name(handler),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )


def _handler_name(handler: Hook[SessionEvent, None]) -> str:
    """Best-effort name for a handler (``__name__`` or its repr)."""
    name = getattr(handler, "__name__", None)
    return name or repr(handler)

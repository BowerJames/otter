"""Fan-out event bus for the agent.

A single :class:`AgentBus` is owned by an :class:`~otter_ai_agent.Agent`. The
driver (and the agent's session-bus handlers) publish
:data:`~otter_ai_agent.events.AgentEvent`\\ s via :meth:`publish`; subscribers
register typed handlers via :meth:`subscribe` and are awaited serially in
registration order.

Dispatch is **inline** (``publish`` awaits every handler before returning),
mirroring pi's listener model. This gives strict event ordering and trivial
``agent.idle()`` semantics (the run task is done only once ``agent_end`` — the
last event — has been dispatched). The tradeoff, the same one
:class:`~otter_ai_core.model_session.ModelSessionBus` documents, is that one
slow subscriber stalls the next event; for v1 (text-only, rendering-fast UI
handlers) this is acceptable. The heavy work (tool execution) runs in the
driver task, not in bus handlers.

Handler failures are contained: a handler that raises is logged and skipped,
so one bad handler cannot kill the run for the rest. (There is no
``HandlerErrorEvent`` here, unlike the session bus — the agent bus is the
top-level app surface and a failed UI handler is an observability concern for
the embedder, not a protocol event.)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from otter_ai_agent.events import AgentEvent, AgentEventType

_logger = logging.getLogger(__name__)

#: A single-argument async handler: ``[AgentEvent] -> Awaitable[None]``.
type AgentHandler = Callable[[AgentEvent], Awaitable[None]]


class AgentBus:
    _handlers: dict[AgentEventType, list[AgentHandler]]

    def __init__(self) -> None:
        self._handlers = {value: [] for value in AgentEventType}

    def subscribe(
        self, event: AgentEventType, handler: AgentHandler
    ) -> Callable[[], None]:
        """Register a handler for an event type. Returns an unsubscribe callable."""
        self._handlers[event].append(handler)
        return lambda: self._unsubscribe(event, handler)

    def subscribe_all(self, handler: AgentHandler) -> Callable[[], None]:
        """Register a handler for **every** event type (used by ``Agent.stream``).

        Returns an unsubscribe callable that removes the handler from all types."""
        for event in AgentEventType:
            self._handlers[event].append(handler)
        return lambda: self._unsubscribe_all(handler)

    def _unsubscribe_all(self, handler: AgentHandler) -> None:
        for event in AgentEventType:
            self._unsubscribe(event, handler)

    async def publish(self, event: AgentEvent) -> None:
        """Dispatch ``event`` to all registered handlers, serially in order.

        A handler that raises is logged and contained; dispatch continues to
        the next handler.
        """
        for handler in self._handlers[event.type]:
            try:
                await handler(event)
            except Exception:  # noqa: BLE001 — contain handler failures.
                _logger.exception(
                    "AgentBus handler %r raised while handling %s",
                    getattr(handler, "__name__", repr(handler)),
                    event.type,
                )

    def _unsubscribe(self, event: AgentEventType, handler: AgentHandler) -> None:
        try:
            self._handlers[event].remove(handler)
        except ValueError:
            pass

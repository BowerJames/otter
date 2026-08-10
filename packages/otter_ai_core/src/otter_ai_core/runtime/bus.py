from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from types import NoneType
from typing import cast

from otter_ai_core.interfaces.capabilities import Channel
from otter_ai_core.interfaces.roles import EventRunner
from otter_ai_core.mixins import TaskRunnerMixIn
from otter_ai_core.runtime.default_channel import create_default_channel

_logger = logging.getLogger(__name__)

#: Erased async-handler shape stored under each registered event name.
type _BusHandler = Callable[[object], Awaitable[None]]


class Bus(TaskRunnerMixIn, EventRunner):
    def __init__(
        self,
        channel_factory: Callable[[], Channel[tuple[str, object]]] = create_default_channel,
    ) -> None:
        self._channel: Channel[tuple[str, object]] = channel_factory()
        # Event names registered via ``register``, mapped to the concrete type
        # every emitted payload must be an instance of. Starts empty: the Bus
        # knows no event types until the owner registers them.
        self._trigger_types: dict[str, type[object]] = {}
        # Heterogeneous subscriber registry: handlers are erased to ``object``
        # and recovered with ``cast`` at the dispatch boundary.
        self._handlers: dict[str, list[object]] = {}

    def register(
        self,
        hook_name: str,
        event_trigger_type: type[object],
        event_response_type: type[object],
    ) -> None:
        # The Bus is the no-response (pub/sub) variant of EventRunner, so a
        # response type other than NoneType is a configuration error.
        if event_response_type is not NoneType:
            raise ValueError("Bus only supports a None event_response_type.")
        if hook_name in self._trigger_types:
            # Always reject re-registration — even an identical one — to keep
            # event-type ownership explicit.
            raise ValueError(f"Event {hook_name!r} is already registered.")
        self._trigger_types[hook_name] = event_trigger_type

    def on(self, type: str, handler: Callable[..., object]) -> Callable[[], None]:
        if type not in self._trigger_types:
            raise ValueError(f"Event {type!r} is not registered.")
        self._handlers.setdefault(type, []).append(handler)
        removed = False

        def _unsubscribe() -> None:
            nonlocal removed
            if removed:
                return
            removed = True
            with contextlib.suppress(ValueError):  # already gone / never added
                self._handlers[type].remove(handler)

        return _unsubscribe

    async def emit(self, type: str, event: object) -> None:
        trigger_type = self._trigger_types.get(type)
        if trigger_type is None:
            raise ValueError(f"Event {type!r} is not registered.")
        if not isinstance(event, trigger_type):
            raise ValueError(
                f"Event {type!r} expects a {trigger_type.__name__}; got {event.__class__.__name__}."
            )
        self._channel.push((type, event))

    async def _run(self) -> None:
        async for type_, event in self._channel:
            for handler in self._handlers.get(type_, ()):
                try:
                    await cast(_BusHandler, handler)(event)
                except Exception:
                    # Isolate the subscriber: log and keep dispatching. Do not
                    # catch BaseException — CancelledError must propagate so the
                    # worker can be torn down on shutdown.
                    _logger.error(
                        "bus handler raised for %r; continuing",
                        type_,
                        exc_info=True,
                    )

    def end(self) -> None:
        self._channel.end()

    def _register_tasks(self, tg: asyncio.TaskGroup) -> None:
        tg.create_task(self._run())


def create_bus() -> Bus:
    return Bus()

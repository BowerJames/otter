from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from otter_ai_core._lifecycle import await_or_cancel
from otter_ai_core.channel import ChannelPair, create_channel

_logger = logging.getLogger(__name__)

_DEFAULT_ACLOSE_TIMEOUT: float = 5.0


@dataclass(frozen=True, slots=True)
class BusEvent[TPayload]:
    name: str


#: The handler signature for ``BusEvent[TPayload]``.
type BusHandler[TPayload] = Callable[[TPayload], Awaitable[None]]


class Bus:
    __slots__ = ("_reader", "_writer", "_handlers", "_task")

    def __init__(self) -> None:
        channel_pair: ChannelPair[tuple[object, object]] = create_channel()
        self._reader = channel_pair.reader
        self._writer = channel_pair.writer
        # Heterogeneous registry: the per-event TPayload relationship cannot be
        # tracked through a runtime dict, so storage is erased to ``object`` and
        # recovered with ``cast`` at the typed API boundary — mirroring
        # :class:`~otter_ai_core.hook_runner.HookRunner`. The public API stays
        # fully type-safe; only the internals are erased.
        self._handlers: dict[object, list[object]] = {}
        self._task: asyncio.Task[None] = asyncio.create_task(self._run())

    async def _run(self) -> None:
        async for event, payload in self._reader:
            for handler in self._handlers.get(event, ()):
                try:
                    await cast(BusHandler[object], handler)(payload)
                except Exception:
                    # Isolate the subscriber: log and keep dispatching. Do not
                    # catch BaseException — CancelledError must propagate so the
                    # worker can be torn down on aclose().
                    _logger.error(
                        "bus handler raised for %r; continuing",
                        event,
                        exc_info=True,
                    )

    def subscribe[TPayload](
        self, event: BusEvent[TPayload], handler: BusHandler[TPayload]
    ) -> Callable[[], None]:
        self._handlers.setdefault(event, []).append(handler)
        removed = False

        def _unsubscribe() -> None:
            nonlocal removed
            if removed:
                return
            removed = True
            with contextlib.suppress(ValueError):  # already gone / never added
                self._handlers[event].remove(handler)

        return _unsubscribe

    def publish[TPayload](self, event: BusEvent[TPayload], payload: TPayload) -> None:
        self._writer.push((event, payload))

    def end(self) -> None:
        self._writer.end()

    async def aclose(self, timeout: float | None = _DEFAULT_ACLOSE_TIMEOUT) -> None:
        self.end()
        await await_or_cancel(self._task, timeout)

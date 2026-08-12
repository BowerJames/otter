from __future__ import annotations

import asyncio
from typing import Self

from otter_ai_core.data_models.events import ClientContextEvent, ServerContextEvent
from otter_ai_core.interfaces.roles.model_connection import ModelConnection


class FakeModelConnection(ModelConnection):
    def __init__(self, idle: bool = True, auto_end: bool = False) -> None:
        self._queue: asyncio.Queue[ServerContextEvent | None] = asyncio.Queue()
        self._idle: bool = idle
        self._auto_end: bool = auto_end
        self._ended: bool = False

    def push(self, event: ClientContextEvent) -> None:
        raise NotImplementedError

    def end(self) -> None:
        if self._auto_end and not self._ended:
            self._queue.put_nowait(None)
        self._ended = True

    def trigger_end(self) -> None:
        if self._auto_end:
            raise RuntimeError("trigger_end() cannot be used when auto_end=True")
        if not self._ended:
            raise RuntimeError("end() must be called before trigger_end()")
        self._queue.put_nowait(None)

    def is_idle(self) -> bool:
        return self._idle

    async def wait_for_idle(self) -> None:
        raise NotImplementedError

    def abort(self) -> None:
        raise NotImplementedError

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> ServerContextEvent:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item

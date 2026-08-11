from __future__ import annotations

import asyncio
from typing import Self

from otter_ai_core.data_models.events import ClientContextEvent, ServerContextEvent
from otter_ai_core.interfaces.roles.model_connection import ModelConnection


class FakeModelConnection(ModelConnection):
    def __init__(self) -> None:
        self._queue: asyncio.Queue[ServerContextEvent | None] = asyncio.Queue()

    def push(self, event: ClientContextEvent) -> None:
        raise NotImplementedError

    def end(self) -> None:
        self._queue.put_nowait(None)

    def is_idle(self) -> bool:
        raise NotImplementedError

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

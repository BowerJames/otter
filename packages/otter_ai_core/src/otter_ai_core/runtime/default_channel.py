from __future__ import annotations

import asyncio
from typing import Self

from otter_ai_core.interfaces import Channel


class _End:
    __slots__ = ()


_END = _End()


class DefaultChannel[TEvent](Channel[TEvent]):
    def __init__(self) -> None:
        self._queue: asyncio.Queue[TEvent | _End] = asyncio.Queue()
        self._done: bool = False
        self._iterating: bool = False

    def push(self, event: TEvent) -> None:
        if self._done:
            return
        self._queue.put_nowait(event)

    def end(self) -> None:
        if self._done:
            return
        self._done = True
        self._queue.put_nowait(_END)

    def __aiter__(self) -> Self:
        if self._iterating:
            raise RuntimeError("DefaultChannel is single-pass: already iterated")
        self._iterating = True
        return self

    async def __anext__(self) -> TEvent:
        item = await self._queue.get()
        if isinstance(item, _End):
            raise StopAsyncIteration
        return item


def create_default_channel[TEvent]() -> Channel[TEvent]:
    return DefaultChannel[TEvent]()


__all__ = [
    "DefaultChannel",
    "create_default_channel",
]

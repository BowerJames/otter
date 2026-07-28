from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Self


class _Core[TEvent]:
    __slots__ = ("queue", "done")

    def __init__(self) -> None:
        self.queue: asyncio.Queue[TEvent | None] = asyncio.Queue()
        self.done: bool = False


class ChannelReader[TEvent]:
    __slots__ = ("_core", "_iterating")

    def __init__(self, core: _Core[TEvent]) -> None:
        self._core = core
        self._iterating = False

    def __aiter__(self) -> Self:
        if self._iterating:
            raise RuntimeError("ChannelReader is single-consumer and single-pass: already iterated")
        self._iterating = True
        return self

    async def __anext__(self) -> TEvent:
        item = await self._core.queue.get()
        if item is None:
            raise StopAsyncIteration
        return item


class ChannelWriter[TEvent]:
    __slots__ = ("_core",)

    def __init__(self, core: _Core[TEvent]) -> None:
        self._core = core

    def push(self, event: TEvent) -> None:
        if self._core.done:
            return
        self._core.queue.put_nowait(event)

    def end(self) -> None:
        if self._core.done:
            return
        self._core.done = True
        self._core.queue.put_nowait(None)


@dataclass(slots=True, frozen=True)
class ChannelPair[TEvent]:
    writer: ChannelWriter[TEvent]
    reader: ChannelReader[TEvent]


def create_channel[TEvent]() -> ChannelPair[TEvent]:
    core = _Core[TEvent]()
    return ChannelPair(
        writer=ChannelWriter[TEvent](core),
        reader=ChannelReader[TEvent](core),
    )

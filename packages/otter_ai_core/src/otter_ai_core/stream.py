from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Self

from otter_ai_core.channel import (
    ChannelPair,
    ChannelReader,
    ChannelWriter,
    create_channel,
)


class StreamClient[TEvent]:
    __slots__ = ("_reader", "_abort_signal")

    def __init__(self, reader: ChannelReader[TEvent], abort_signal: asyncio.Event) -> None:
        self._reader = reader
        self._abort_signal = abort_signal

    def abort(self) -> None:
        self._abort_signal.set()

    def __aiter__(self) -> Self:
        # Serve as our own async iterator so both ``async for`` and direct
        # ``anext()`` are supported (the connection adapter drives streams with
        # ``anext()`` directly, not ``async for``). Triggering the reader's
        # ``__aiter__`` honours its single-pass guard: a second ``async for``
        # raises :class:`RuntimeError`.
        self._reader.__aiter__()
        return self

    async def __anext__(self) -> TEvent:
        return await anext(self._reader)


class StreamBackend[TEvent]:
    __slots__ = ("_writer", "_abort_signal")

    def __init__(self, writer: ChannelWriter[TEvent], abort_signal: asyncio.Event) -> None:
        self._writer = writer
        self._abort_signal = abort_signal

    @property
    def abort_signal(self) -> asyncio.Event:
        return self._abort_signal

    def push(self, event: TEvent) -> None:
        self._writer.push(event)

    def end(self) -> None:
        self._writer.end()


@dataclass(slots=True, frozen=True)
class StreamPair[TEvent]:
    client: StreamClient[TEvent]
    backend: StreamBackend[TEvent]


def create_stream_pair[TEvent]() -> StreamPair[TEvent]:
    channel: ChannelPair[TEvent] = create_channel()
    abort_signal: asyncio.Event = asyncio.Event()
    return StreamPair(
        client=StreamClient(channel.reader, abort_signal),
        backend=StreamBackend(channel.writer, abort_signal),
    )

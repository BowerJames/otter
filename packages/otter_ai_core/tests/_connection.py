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


class BidirectionalChannelClient[TClient, TBackend]:
    __slots__ = ("_inbound", "_outbound")

    def __init__(self, inbound: ChannelReader[TBackend], outbound: ChannelWriter[TClient]) -> None:
        self._inbound = inbound
        self._outbound = outbound

    def __aiter__(self) -> Self:
        # Delegate to the inbound reader's ``__aiter__`` so its single-pass
        # guard fires on a second iteration.
        self._inbound.__aiter__()
        return self

    async def __anext__(self) -> TBackend:
        return await anext(self._inbound)

    def push(self, event: TClient) -> None:
        self._outbound.push(event)

    def end(self) -> None:
        self._outbound.end()


class BidirectionalChannelBackend[TClient, TBackend]:
    __slots__ = ("_inbound", "_outbound")

    def __init__(self, inbound: ChannelWriter[TBackend], outbound: ChannelReader[TClient]) -> None:
        self._inbound = inbound
        self._outbound = outbound

    def __aiter__(self) -> Self:
        # Delegate to the outbound reader's ``__aiter__`` so its single-pass
        # guard fires on a second iteration.
        self._outbound.__aiter__()
        return self

    async def __anext__(self) -> TClient:
        return await anext(self._outbound)

    def push(self, event: TBackend) -> None:
        self._inbound.push(event)

    def end(self) -> None:
        self._inbound.end()


@dataclass(slots=True, frozen=True)
class BidirectionalChannelPair[TClient, TBackend]:
    client: BidirectionalChannelClient[TClient, TBackend]
    backend: BidirectionalChannelBackend[TClient, TBackend]


def create_bidirectional_channel[TClient, TBackend]() -> BidirectionalChannelPair[
    TClient, TBackend
]:
    inbound: ChannelPair[TBackend] = create_channel()
    outbound: ChannelPair[TClient] = create_channel()
    return BidirectionalChannelPair(
        client=BidirectionalChannelClient(inbound.reader, outbound.writer),
        backend=BidirectionalChannelBackend(inbound.writer, outbound.reader),
    )


class ConnectionClient[TClient, TBackend]:
    __slots__ = ("_client", "_abort_signal")

    def __init__(
        self,
        client: BidirectionalChannelClient[TClient, TBackend],
        abort_signal: asyncio.Event,
    ) -> None:
        self._client = client
        self._abort_signal = abort_signal

    def abort(self) -> None:
        self._abort_signal.set()
        self.end()

    def push(self, event: TClient) -> None:
        self._client.push(event)

    def end(self) -> None:
        self._client.end()

    def __aiter__(self) -> Self:
        # Delegate to the underlying client's ``__aiter__`` so the inbound
        # reader's single-pass guard fires on a second iteration.
        self._client.__aiter__()
        return self

    async def __anext__(self) -> TBackend:
        return await anext(self._client)


class ConnectionBackend[TClient, TBackend]:
    __slots__ = ("_backend", "_abort_signal")

    def __init__(
        self,
        backend: BidirectionalChannelBackend[TClient, TBackend],
        abort_signal: asyncio.Event,
    ) -> None:
        self._backend = backend
        self._abort_signal = abort_signal

    @property
    def abort_signal(self) -> asyncio.Event:
        return self._abort_signal

    async def wait_for_abort(self) -> None:
        await self._abort_signal.wait()

    def push(self, event: TBackend) -> None:
        self._backend.push(event)

    def end(self) -> None:
        self._backend.end()

    def __aiter__(self) -> Self:
        # Delegate to the underlying backend's ``__aiter__`` so the outbound
        # reader's single-pass guard fires on a second iteration.
        self._backend.__aiter__()
        return self

    async def __anext__(self) -> TClient:
        return await anext(self._backend)


@dataclass(slots=True, frozen=True)
class ConnectionPair[TClient, TBackend]:
    client: ConnectionClient[TClient, TBackend]
    backend: ConnectionBackend[TClient, TBackend]


def create_connection[TClient, TBackend]() -> ConnectionPair[TClient, TBackend]:
    channel: BidirectionalChannelPair[TClient, TBackend] = create_bidirectional_channel()
    abort_signal: asyncio.Event = asyncio.Event()
    return ConnectionPair(
        client=ConnectionClient(channel.client, abort_signal),
        backend=ConnectionBackend(channel.backend, abort_signal),
    )

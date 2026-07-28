from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Self

from otter_ai_core.bidirectional_channel import (
    BidirectionalChannelBackend,
    BidirectionalChannelClient,
    BidirectionalChannelPair,
    create_bidirectional_channel,
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
        # reader's single-pass guard fires on a second iteration (matching
        # ``StreamClient``).
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

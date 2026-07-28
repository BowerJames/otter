from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from otter_ai_core.channel import (
    ChannelPair,
    ChannelReader,
    ChannelWriter,
    create_channel,
)


class BidirectionalChannelClient[TClient, TBackend]:
    __slots__ = ("_inbound", "_outbound")

    def __init__(self, inbound: ChannelReader[TBackend], outbound: ChannelWriter[TClient]) -> None:
        self._inbound = inbound
        self._outbound = outbound

    def __aiter__(self) -> Self:
        # Delegate to the inbound reader's ``__aiter__`` so its single-pass
        # guard fires on a second iteration (matching ``StreamClient``).
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
        # guard fires on a second iteration (matching ``StreamClient``).
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

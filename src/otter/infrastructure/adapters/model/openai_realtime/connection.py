"""The connection a realtime model is spoken to over, and how one is opened."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from openai import AsyncOpenAI
from openai.types.realtime import RealtimeClientEventParam, RealtimeServerEvent


class RealtimeConnection(Protocol):
    """One open connection to a realtime endpoint: events go out, and events come back."""

    async def send(self, event: RealtimeClientEventParam) -> None: ...

    def __aiter__(self) -> AsyncIterator[RealtimeServerEvent]:
        """The events the endpoint sends, as they arrive, until the connection closes."""
        ...


type RealtimeConnect = Callable[[str], AbstractAsyncContextManager[RealtimeConnection]]
"""Opens a connection for a conversation with the named model; leaving it closes it."""


class OpenAIConnect:
    """Opens connections to OpenAI's realtime endpoint, authenticated with `api_key`."""

    def __init__(self, api_key: str) -> None:
        # The base URL is given outright: left out, the client would take it from the
        # environment.
        self._client = AsyncOpenAI(base_url="https://api.openai.com/v1", api_key=api_key)

    def __call__(self, model_name: str) -> AbstractAsyncContextManager[RealtimeConnection]:
        return self._client.realtime.connect(model=model_name)

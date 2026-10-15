"""A model served over OpenAI's realtime endpoint."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack

from openai.types.realtime import RealtimeServerEvent, RealtimeSessionCreateRequestParam

from otter.core.domain.messages import AssistantMessage, ContextEntry
from otter.core.model import ModelInput, ModelPort

from .connection import RealtimeConnect, RealtimeConnection
from .errors import ModelFailed, TurnCutOff
from .wire import items_of, session_of, turn_of


class OpenAIRealtimeAdapter(ModelPort):
    """The model `model_name`, spoken to over a connection `connect` opens.

    The connection is made on opening, kept between turns, and closed on closing. The
    endpoint holds the conversation while the connection lasts, so a turn whose context
    goes on from the turn before sends only what was added since. Any other context is
    sent whole over a new connection, as it is after a turn that fails or is abandoned:
    the endpoint's copy can then no longer be trusted.

    The model writes its turns as text. Images are sent only when carried inline, and
    audio only as 16-bit mono wav at 24 kHz, the one form the endpoint takes without
    converting: a short note goes in place of anything else.
    """

    def __init__(self, connect: RealtimeConnect, model_name: str) -> None:
        self._connect = connect
        self._model_name = model_name
        self._opened = AsyncExitStack()
        self._connection: RealtimeConnection | None = None
        self._events: AsyncIterator[RealtimeServerEvent] | None = None
        # What the endpoint holds over the current connection.
        self._session: RealtimeSessionCreateRequestParam | None = None
        self._held: list[ContextEntry] = []

    async def open(self) -> None:
        try:
            await self._connected()
        except BaseException:
            await self._disconnect()
            raise

    async def close(self) -> None:
        await self._disconnect()

    async def generate(self, model_input: ModelInput) -> AssistantMessage:
        """Send what the endpoint lacks of `model_input` and return the turn the model takes.

        The endpoint reporting an error, or that the model failed, raises `ModelFailed`;
        the connection closing before the turn is done raises `TurnCutOff`. Tool
        arguments that are not valid JSON raise `json.JSONDecodeError`.
        """
        context = list(model_input.context)
        if context[: len(self._held)] != self._held:
            await self._disconnect()
        done = False
        try:
            connection, events = await self._connected()
            session = session_of(model_input.system, model_input.tools)
            if session != self._session:
                await connection.send({"type": "session.update", "session": session})
                self._session = session
            for entry in context[len(self._held) :]:
                for item in items_of(entry):
                    await connection.send({"type": "conversation.item.create", "item": item})
            self._held = context
            await connection.send({"type": "response.create"})
            async for event in events:
                if event.type == "error":
                    raise ModelFailed(event.error.message)
                if event.type == "response.done":
                    turn = turn_of(event.response)
                    # The endpoint already holds the turn it produced.
                    self._held = [*context, turn]
                    done = True
                    return turn
            raise TurnCutOff()
        finally:
            if not done:
                await self._disconnect()

    async def _connected(self) -> tuple[RealtimeConnection, AsyncIterator[RealtimeServerEvent]]:
        if self._connection is None or self._events is None:
            self._connection = await self._opened.enter_async_context(
                self._connect(self._model_name)
            )
            self._events = aiter(self._connection)
        return self._connection, self._events

    async def _disconnect(self) -> None:
        # Forgotten before it is closed, so a connection that fails to close is not used
        # again.
        opened, self._opened = self._opened, AsyncExitStack()
        self._connection = self._events = None
        self._session = None
        self._held = []
        await opened.aclose()

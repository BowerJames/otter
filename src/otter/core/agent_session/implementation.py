"""An agent session: a conversation with a model, driven by a queue of prompts."""

import asyncio
from collections import deque
from collections.abc import AsyncGenerator, Sequence
from contextlib import aclosing
from types import TracebackType
from typing import Self

from otter.core.domain.messages import (
    AssistantMessage,
    AudioPart,
    ContextEntry,
    ImagePart,
    ImageUrlPart,
    TextPart,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    UserPart,
)

from .data import Idle, SessionEvent
from .errors import AlreadyStreaming, SessionEnded
from .port import AgentSessionPort


class AgentSessionImpl:
    """One ongoing agent session, run in the world `port` gives it.

    Each tool call the model asks for is run as it is reached, one at a time and in the
    order the model asked, and its result is shown to the model. Everything that joins
    the conversation is recorded as it joins, before it is yielded.

    The session starts with the context `port` gives it, so it picks up where that
    leaves off: if it ends with something the model has not answered, the model answers
    it once the session is streamed.

    Failures leave the session as it was wherever they can. A prompt that cannot be
    recorded stays queued. Before the model's turn has joined the conversation, or once
    every tool call of it has its result, a failure propagates and the session is as it
    was, so streaming again picks up from there. Part-way through, the model's turn
    can no longer be taken back, so a failure ends the session.
    """

    def __init__(self, port: AgentSessionPort) -> None:
        self._port = port
        self._history: list[ContextEntry] = []
        self._entered = False
        self._queued: deque[tuple[UserPart, ...]] = deque()
        # Whether the model owes a turn: the history ends in something it has not answered.
        self._owed = False
        self._wake = asyncio.Event()
        self._at_rest = asyncio.Event()
        self._at_rest.set()
        self._ended = False
        self._streaming = False
        # What entering raised, for the stream that was waiting on it to raise in turn.
        self._waiting_to_enter = False
        self._failed_to_enter: Exception | None = None

    def prompt(
        self,
        text: str,
        *,
        images: Sequence[ImagePart | ImageUrlPart] = (),
        audio: Sequence[AudioPart] = (),
    ) -> None:
        if self._ended:
            raise SessionEnded()
        self._queued.append((TextPart(text), *images, *audio))
        self._at_rest.clear()
        self._wake.set()

    async def stream(self) -> AsyncGenerator[SessionEvent, None]:
        if self._streaming:
            raise AlreadyStreaming()
        self._streaming = True
        try:
            await self._until_entered()
            while not self._ended:
                while self._queued:
                    content = self._queued.popleft()
                    prompt = UserMessage(content)
                    try:
                        self._port.record(prompt)
                    except BaseException:
                        # A prompt that cannot be recorded is still queued.
                        if not self._ended:
                            self._queued.appendleft(content)
                        raise
                    self._history.append(prompt)
                    self._owed = True
                    yield await self._told(prompt)
                if not self._owed:
                    await self._port.before_idle()
                    if self._queued or self._ended:
                        continue
                    self._at_rest.set()
                    yield await self._told(Idle())
                    while not self._queued and not self._ended:
                        self._wake.clear()
                        await self._wake.wait()
                    continue
                # Closed with the stream, so a stream abandoned part-way through the
                # model's turn is abandoned there too.
                async with aclosing(self._models_turn()) as events:
                    async for event in events:
                        yield event
        finally:
            self._streaming = False

    async def _models_turn(self) -> AsyncGenerator[SessionEvent, None]:
        """Have the model take its turn, and run each tool call it asks for."""
        turn = await self._port.generate(tuple(self._history))
        calls = [part for part in turn.content if isinstance(part, ToolCall)]
        joined = False
        answered = 0
        try:
            self._port.record(turn)
            self._history.append(turn)
            self._owed = bool(calls)
            joined = True
            yield await self._told(turn)
            for call in calls:
                result = ToolResultMessage(call.id, await self._port.run_tool(call))
                self._port.record(result)
                self._history.append(result)
                answered += 1
                yield await self._told(result)
        except BaseException:
            # A tool call left without a result is a history no provider will accept,
            # and the model's turn cannot be taken back; nor can a turn the model took
            # that could not be recorded.
            if not joined or answered < len(calls):
                self.end()
            raise

    async def _told[Event: SessionEvent](self, event: Event) -> Event:
        """Tell the port of `event`, and return it for the stream to yield."""
        await self._port.on_event(event)
        return event

    async def _until_entered(self) -> None:
        """Wait for the session to be entered, or ended.

        Raises what entering raised if it failed while this was waiting.
        """
        self._waiting_to_enter = True
        try:
            while not self._entered and not self._ended:
                if self._failed_to_enter is not None:
                    raise self._failed_to_enter
                self._wake.clear()
                await self._wake.wait()
        finally:
            self._waiting_to_enter = False
            self._failed_to_enter = None

    def history(self) -> Sequence[ContextEntry]:
        return tuple(self._history)

    async def wait_for_idle(self) -> None:
        await self._at_rest.wait()

    def end(self) -> None:
        self._ended = True
        self._queued.clear()
        self._at_rest.set()
        self._wake.set()

    async def __aenter__(self) -> Self:
        try:
            context = await self._port.start(self)
        except Exception as error:
            if self._waiting_to_enter:
                self._failed_to_enter = error
                self._wake.set()
            raise
        self._history = list(context)
        self._owed = bool(context) and not isinstance(context[-1], AssistantMessage)
        self._entered = True
        self._wake.set()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.end()
        if self._entered:
            self._entered = False
            await self._port.stop()

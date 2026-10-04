"""An agent session run on a model spoken to through a conversation."""

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Sequence

from otter.agent_session import (
    AgentTool,
    AssistantTurn,
    Idle,
    SessionEvent,
    ToolResult,
    UserTurn,
)
from otter.messages import (
    AudioPart,
    ImagePart,
    ImageUrlPart,
    TextPart,
    ToolCall,
    ToolSpec,
    UserPart,
)
from otter.model import Model


class ChatCompletionsAgentSession:
    """One ongoing agent session: prompts are queued, and `stream` does the work.

    The session holds one conversation with `model`, started with `system` as its system
    prompt. `tools` are what the model
    may ask to have run; each is run when asked for, one at a time and in the order the
    model asked, and its result is shown to the model.

    Nothing happens unless `stream` is being read: the session advances only as its
    events are taken.
    """

    def __init__(
        self,
        model: Model,
        *,
        system: str | None = None,
        tools: Sequence[AgentTool] = (),
    ) -> None:
        self._conversation = model(
            system, [ToolSpec(tool.name, tool.description, tool.parameters) for tool in tools]
        )
        self._tools = {tool.name: tool for tool in tools}
        self._queued: deque[tuple[UserPart, ...]] = deque()
        # Whether the model owes a turn: the history ends in something it has not answered.
        self._owed = False
        self._wake = asyncio.Event()
        self._at_rest = asyncio.Event()
        self._at_rest.set()
        self._ended = False
        self._streaming = False

    def prompt(
        self,
        text: str,
        *,
        images: Sequence[ImagePart | ImageUrlPart] = (),
        audio: Sequence[AudioPart] = (),
    ) -> None:
        """Queue a user turn: `text`, then `images`, then `audio`. Returns at once.

        The turn joins the conversation at the next point the model can take it: straight
        away if the session is at rest, otherwise once every tool call of the model's
        current turn has its result. Queued turns join in the order they were made.
        Raises `RuntimeError` if the session has ended.
        """
        if self._ended:
            raise RuntimeError("the session has ended")
        self._queued.append((TextPart(text), *images, *audio))
        self._at_rest.clear()
        self._wake.set()

    async def stream(self) -> AsyncIterator[SessionEvent]:
        """Run the session, yielding each thing that happens in it as it happens.

        The stream does not finish when the model does: it yields `Idle` and waits for
        the next prompt. It finishes once the session has ended. A session has one
        stream at a time: reading a second while the first is live raises `RuntimeError`.

        If the model fails to produce a turn, the error propagates and the session is as
        it was, so streaming again retries. If a tool fails, the error propagates and the
        session has ended: the model's turn is left asking for a result it never got.
        The same holds if the stream is abandoned or cancelled part-way through a turn's
        tool calls; use `end` to stop cleanly.
        """
        if self._streaming:
            raise RuntimeError("the session is already being streamed")
        self._streaming = True
        try:
            while not self._ended:
                while self._queued:
                    content = self._queued.popleft()
                    self._conversation.add_user_message(content)
                    self._owed = True
                    yield UserTurn(content)
                if not self._owed:
                    self._at_rest.set()
                    yield Idle()
                    while not self._queued and not self._ended:
                        self._wake.clear()
                        await self._wake.wait()
                    continue
                message = await self._conversation.generate()
                calls = [part for part in message.content if isinstance(part, ToolCall)]
                self._owed = bool(calls)
                answered = 0
                try:
                    yield AssistantTurn(message)
                    for call in calls:
                        text = await self._tools[call.name].execute(call.arguments)
                        self._conversation.add_tool_result(call.id, text)
                        answered += 1
                        yield ToolResult(call.id, text)
                except BaseException:
                    # A tool call left without a result is a history no provider will
                    # accept, and the conversation cannot take the model's turn back.
                    if answered < len(calls):
                        self.end()
                    raise
        finally:
            self._streaming = False

    async def wait_for_idle(self) -> None:
        """Wait until the session is at rest: nothing queued and the model owed nothing.

        Returns at once if it already is, and also once the session has ended. A prompt
        just made counts as work outstanding, so prompting and then waiting waits for
        that prompt to be answered. The session only advances while `stream` is being
        read, so this is for a task other than the one reading it: with no reader, or
        after the stream has raised, the wait does not finish.
        """
        await self._at_rest.wait()

    def end(self) -> None:
        """End the session. Returns at once; ending an ended session does nothing.

        A turn the model is part-way through is finished, its tool calls included, and
        then the stream finishes without the model being asked again. Prompts still
        queued are dropped.
        """
        self._ended = True
        self._queued.clear()
        self._at_rest.set()
        self._wake.set()

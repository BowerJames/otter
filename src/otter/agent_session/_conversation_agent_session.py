"""An agent session run on a model spoken to through a conversation."""

import asyncio
from collections import deque
from collections.abc import AsyncGenerator, Sequence
from types import TracebackType
from typing import Self, cast

from otter.conversation import Conversation
from otter.core.domain.messages import (
    AssistantMessage,
    AudioPart,
    ImagePart,
    ImageUrlPart,
    TextPart,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
    UserPart,
)
from otter.model import Model
from otter.session_manager import SessionManager

from ._agent_session import (
    AgentSession,
    AgentTool,
    AssistantTurn,
    Idle,
    SessionEvent,
    ToolResult,
    UserTurn,
)
from ._plugin import Plugin, SessionSetup, ToolOutcome, UnknownTool


def create_conversation_agent_session(
    model: Model,
    session_manager: SessionManager,
    *,
    system: str | None = None,
    tools: Sequence[AgentTool] = (),
    plugins: Sequence[Plugin] = (),
) -> AgentSession:
    """Start an agent session on `model`, its context kept in `session_manager`.

    The session holds one conversation with `model`, started with `system` as its system
    prompt. `tools` are what the model may ask to have run; each is run when asked for,
    one at a time and in the order the model asked, and its result is shown to the model.

    The conversation starts out with the entries `session_manager` holds, so the session
    picks up where they leave off: if they end with something the model has not
    answered, it is answered once the session is streamed. Everything that then joins
    the conversation is appended to `session_manager` as it joins.

    Entering the session starts the conversation and enters it, which may then hold a
    connection to the model open, and leaving the session ends it and leaves the
    conversation. A stream read before the session is entered waits for that.

    `plugins` are asked at each of their hooks, in the order given (see `Plugin`). On
    entry each may change `system` and `tools` before the model is started with them:
    two tools of one name then raise `ValueError`. Make the plugins for this session
    alone: a plugin holds one session's state.
    """
    return ConversationAgentSession(
        model, session_manager, system=system, tools=tools, plugins=plugins
    )


class ConversationAgentSession:
    """One ongoing agent session: prompts are queued, and `stream` does the work.

    The session holds one conversation with `model`, started with `system` as its system
    prompt. `tools` are what the model may ask to have run; each is run when asked for,
    one at a time and in the order the model asked, and its result is shown to the model.
    `plugins` are asked at each of their hooks, in the order given, and on entry may
    change `system` and `tools` before the model is started with them.

    The conversation starts out with the entries `session_manager` holds, so the session
    picks up where they leave off: if they end with something the model has not
    answered, it is answered once the session is streamed. Everything that then joins
    the conversation is appended to `session_manager` as it joins.

    Nothing happens unless `stream` is being read: the session advances only as its
    events are taken.

    The session is an async context manager: entering it starts the conversation and
    enters it, which may then hold a connection to the model open, and leaving it ends
    it and leaves the conversation. A stream read before then waits to be entered.
    """

    def __init__(
        self,
        model: Model,
        session_manager: SessionManager,
        *,
        system: str | None = None,
        tools: Sequence[AgentTool] = (),
        plugins: Sequence[Plugin] = (),
    ) -> None:
        self._model = model
        self._session_manager = session_manager
        self._setup = SessionSetup(system, tuple(tools))
        self._plugins = tuple(plugins)
        # Made on entry, once the plugins have had their say on the setup.
        self._conversation: Conversation | None = None
        self._tools: dict[str, AgentTool] = {}
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

    async def stream(self) -> AsyncGenerator[SessionEvent, None]:
        """Run the session, yielding each thing that happens in it as it happens.

        The stream does not finish when the model does: it yields `Idle` and waits for
        the next prompt. It finishes once the session has ended. A session has one
        stream at a time: reading a second while the first is live raises `RuntimeError`.

        Until the session is entered the stream yields nothing and waits. If entering
        fails while it waits, it raises what entering raised.

        If the model fails to produce a turn, the error propagates and the session is as
        it was, so streaming again retries. If a tool fails, or the model asks for one
        the session does not have (`UnknownTool`), and no plugin returns text for it,
        the error propagates and the session has ended: the model's turn is left asking
        for a result it never got. The same holds if the stream is abandoned or
        cancelled part-way through a turn's tool calls; use `end` to stop cleanly.

        If a plugin's hook raises, the error propagates. Before the session comes to
        rest, the session is as it was, so streaming again asks the plugins again; part-
        way through a turn's tool calls, the session has ended.

        If the session manager fails to take a prompt, the error propagates and the
        session is as it was, the prompt still queued, so streaming again retries. If it
        fails to take the model's turn or a tool's result, the error propagates and the
        session has ended.
        """
        if self._streaming:
            raise RuntimeError("the session is already being streamed")
        self._streaming = True
        try:
            conversation = await self._entered_conversation()
            while not self._ended:
                while self._queued:
                    content = self._queued[0]
                    # Stored before it leaves the queue, so a prompt that cannot be
                    # stored is still queued.
                    self._session_manager.append(UserMessage(content))
                    self._queued.popleft()
                    conversation.add_user_message(content)
                    self._owed = True
                    yield await self._told(UserTurn(content))
                if not self._owed:
                    for plugin in self._plugins:
                        await plugin.before_idle(self)
                    # A plugin may have prompted the session, or ended it.
                    if self._queued or self._ended:
                        continue
                    self._at_rest.set()
                    yield await self._told(Idle())
                    while not self._queued and not self._ended:
                        self._wake.clear()
                        await self._wake.wait()
                    continue
                message = await conversation.generate()
                calls = [part for part in message.content if isinstance(part, ToolCall)]
                self._owed = bool(calls)
                stored = False
                answered = 0
                try:
                    self._session_manager.append(message)
                    stored = True
                    yield await self._told(AssistantTurn(message))
                    for call in calls:
                        text = await self._run_tool(call)
                        self._session_manager.append(ToolResultMessage(call.id, text))
                        conversation.add_tool_result(call.id, text)
                        answered += 1
                        yield await self._told(ToolResult(call.id, text))
                except BaseException:
                    # A tool call left without a result is a history no provider will
                    # accept, and the conversation cannot take the model's turn back:
                    # nor can it if the turn could not be stored.
                    if not stored or answered < len(calls):
                        self.end()
                    raise
        finally:
            self._streaming = False

    async def _told[Event: SessionEvent](self, event: Event) -> Event:
        """Tell every plugin of `event`, and return it for the stream to yield."""
        for plugin in self._plugins:
            await plugin.on_event(self, event)
        return event

    async def _run_tool(self, call: ToolCall) -> str:
        """Have the tool `call` asks for run, and return the text the model is shown for it.

        Raises the error the call came out with, if no plugin returned text for it.
        """
        reasons: list[str] = []
        for plugin in self._plugins:
            denial = await plugin.before_tool(self, call)
            if denial is not None:
                reasons.append(denial.reason)
        if reasons:
            return "\n".join(reasons)
        outcome: ToolOutcome
        tool = self._tools.get(call.name)
        if tool is None:
            outcome = UnknownTool(call.name)
        else:
            try:
                outcome = await tool.execute(call.arguments)
            except Exception as error:
                outcome = error
        for plugin in self._plugins:
            outcome = await plugin.after_tool(self, call, outcome)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def _entered_conversation(self) -> Conversation:
        """Wait for the session to be entered, and return the conversation it then holds.

        Raises what entering raised if it failed while this was waiting. If the session
        ends unentered, returns a conversation that is never used.
        """
        self._waiting_to_enter = True
        try:
            while self._conversation is None and not self._ended:
                if self._failed_to_enter is not None:
                    error, self._failed_to_enter = self._failed_to_enter, None
                    raise error
                self._wake.clear()
                await self._wake.wait()
        finally:
            self._waiting_to_enter = False
            self._failed_to_enter = None
        return cast(Conversation, self._conversation)

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

    async def __aenter__(self) -> Self:
        """Enter the session, which is returned: `async with session:` scopes its life.

        Its model is started on a conversation, which is entered, and a stream waiting
        for that begins to run. If any of it fails, the error propagates, here and from
        a stream that was waiting, and the session has not been entered: it is as it
        was, and may be entered again.
        """
        try:
            setup = self._setup
            for plugin in self._plugins:
                setup = await plugin.before_start(self, setup)
            tools: dict[str, AgentTool] = {}
            for tool in setup.tools:
                if tool.name in tools:
                    raise ValueError(f"two tools are named {tool.name!r}")
                tools[tool.name] = tool
            context = self._session_manager.entries()
            conversation = self._model(
                setup.system_prompt,
                [ToolSpec(tool.name, tool.description, tool.parameters) for tool in setup.tools],
                context,
            )
            await conversation.__aenter__()
        except Exception as error:
            if self._waiting_to_enter:
                self._failed_to_enter = error
                self._wake.set()
            raise
        self._tools = tools
        self._owed = bool(context) and not isinstance(context[-1], AssistantMessage)
        self._conversation = conversation
        self._wake.set()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave the session: it is ended, its plugins are asked `after_end`, and its
        conversation is left.

        Leave once the stream is no longer being read: a turn the model is part-way
        through elsewhere is cut short by the conversation being left under it. If
        leaving the conversation fails, the error propagates and the session has ended
        all the same.
        """
        self.end()
        if self._conversation is None:
            return
        try:
            for plugin in self._plugins:
                await plugin.after_end(self)
        finally:
            await self._conversation.__aexit__(exc_type, exc, traceback)

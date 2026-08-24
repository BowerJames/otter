import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from enum import Enum, auto
from types import TracebackType
from typing import Self, cast

from otter_ai_core.agent import Agent, AgentOptions, AgentStream
from otter_ai_core.agent.agent_tool.interface import AgentTool
from otter_ai_core.model_registry import ModelRegistry
from otter_ai_core.model_registry.tool_spec.interface import ToolSpec
from otter_ai_core.types import (
    AssistantMessage,
    ToolResultMessage,
    UserMessage,
)

from .session_manager import SessionManager
from .types import AgentSessionEvent


class _SessionState(Enum):
    NEW = auto()
    OPEN = auto()
    CLOSED = auto()


class _ChannelClosed:
    """Sentinel: no further events will appear on the channel."""


class AgentSession:
    """A durable conversational session with an agent.

    Entering the session opens the session manager, replays its existing
    messages as the model's initial context, resolves and enters a model
    via the registry, and builds the agent. Every message produced by a
    run is appended to the session manager as it is produced, so the log
    is a faithful record even if a run fails partway. Runs are driven to
    completion once started, even with no consumer iterating the session.
    Exiting waits for the active run to end, exits the model, then closes
    the session manager; when exit completes, everything recorded is
    durably persisted."""

    def __init__(
        self,
        model: str,
        provider: str,
        system_prompt: str,
        tools: list[AgentTool],
        session_manager: SessionManager,
        model_registry: ModelRegistry,
        agent_options: AgentOptions | None = None,
    ) -> None:
        """Stores the session inputs. `tools` is copied. Performs no I/O
        and resolves nothing; the registry, session manager, and model are
        first touched at __aenter__. `agent_options` defaults to default
        options when omitted."""
        self._model_name = model
        self._provider = provider
        self._system_prompt = system_prompt
        self._tools = list(tools)
        self._session_manager = session_manager
        self._model_registry = model_registry
        self._agent_options = agent_options
        self._state = _SessionState.NEW
        self._exit_stack: AsyncExitStack | None = None
        self._agent: Agent | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._poisoned = False
        self._channel_closed = False
        self._iterator_claimed = False
        self._channel: asyncio.Queue[AgentSessionEvent | BaseException | _ChannelClosed] = (
            asyncio.Queue()
        )

    async def __aenter__(self) -> Self:
        """Opens the session: opens the session manager, reads its
        messages, resolves the model factory from the registry, calls the
        factory with the system prompt, tools, and replayed messages, and
        enters the returned model. Raises on any failure after unwinding
        everything already entered, leaving no half-open session. Registry
        errors (KeyError for unknown provider, model, or missing API key)
        propagate as-is. A session can only be entered once; re-entering
        raises RuntimeError."""
        if self._state is not _SessionState.NEW:
            raise RuntimeError(
                "AgentSession can only be entered once; construct a new AgentSession"
            )
        stack = AsyncExitStack()
        try:
            await self._session_manager.__aenter__()
            stack.push_async_exit(self._session_manager.__aexit__)
            replayed = list(await self._session_manager.get_messages())
            factory = await self._model_registry.get_model_factory(self._provider, self._model_name)
            # AgentTool satisfies ToolSpec structurally; the cast bridges list
            # invariance at the seam between the two abstractions
            model = factory(self._system_prompt, cast(list[ToolSpec], self._tools), replayed)
            await model.__aenter__()
            stack.push_async_exit(model.__aexit__)
        except BaseException:
            self._state = _SessionState.CLOSED
            await stack.aclose()
            raise
        self._exit_stack = stack
        self._agent = Agent(model, self._tools, options=self._agent_options)
        self._state = _SessionState.OPEN
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Closes the session. Waits for the active run to end — its
        events are still delivered to the session's channel first — then
        exits the model, then closes the session manager. Never suppresses
        exceptions from the session body. When this completes, every
        recorded message is durably persisted."""
        if self._run_task is not None:
            await self._run_task
        await self._close_channel()
        if self._exit_stack is not None:
            await self._exit_stack.__aexit__(exc_type, exc_value, traceback)
        self._state = _SessionState.CLOSED

    def __aiter__(self) -> AsyncIterator[AgentSessionEvent]:
        """Iterates the session's event channel: the events of every run,
        in Agent's vocabulary (AgentStart, session messages, AgentTurnStart
        and AgentTurnEnd, AgentEnd per run), across the session's whole
        lifetime. Single consumer: iterating again raises RuntimeError.
        Iteration ends when the session exits; consumption must therefore
        be concurrent with session exit, or iteration will never end.
        Raises RuntimeError outside an open session."""
        self._require_open("__aiter__")
        if self._iterator_claimed:
            raise RuntimeError(
                "AgentSession channel is single-consumer; construct a new AgentSession "
                "to observe another session"
            )
        self._iterator_claimed = True
        return self

    async def __anext__(self) -> AgentSessionEvent:
        item = await self._channel.get()
        if isinstance(item, _ChannelClosed):
            raise StopAsyncIteration
        if isinstance(item, BaseException):
            raise item
        return item

    def prompt(self, text: str) -> None:
        """Starts a run seeded with `text` when the session is idle;
        queues `text` as steering for the active run's next generation
        otherwise. Raises RuntimeError outside an open session, and after
        a run has failed. Returns immediately; events are observed by
        iterating the session."""
        self._require_open("prompt")
        if self._poisoned:
            raise RuntimeError("cannot prompt: the session's previous run failed")
        assert self._agent is not None
        if self._run_active():
            self._agent.steer(text)
            return
        # the agent run starts synchronously so a back-to-back prompt sees
        # an active run and steers rather than colliding with a new one
        stream = self._agent.prompt(text)
        self._run_task = asyncio.create_task(self._drive_run(stream))

    def is_idle(self) -> bool:
        """Returns whether the session has no active run. True exactly
        when a new run may be started with `prompt`."""
        if self._poisoned:
            return False
        return not self._run_active()

    async def wait_for_idle(self) -> None:
        """Waits until the session is idle. Returns immediately when
        already idle; the active run's events are delivered to the
        channel before the wait completes, however the run ends."""
        if self._run_task is not None:
            await self._run_task

    async def _drive_run(self, stream: AgentStream) -> None:
        try:
            async for event in stream:
                # the SessionMessage alias cannot be used with isinstance; its
                # members are checked directly
                if isinstance(event, (UserMessage, AssistantMessage, ToolResultMessage)):
                    await self._session_manager.append_message(event)
                await self._channel.put(event)
        except Exception as error:
            # the run's failure surfaces once, at the channel, and ends it
            self._poisoned = True
            await self._channel.put(error)
            await self._close_channel()

    async def _close_channel(self) -> None:
        if not self._channel_closed:
            self._channel_closed = True
            await self._channel.put(_ChannelClosed())

    def _run_active(self) -> bool:
        return self._run_task is not None and not self._run_task.done()

    def _require_open(self, action: str) -> None:
        if self._state is not _SessionState.OPEN:
            raise RuntimeError(
                f"{action}() called outside an open session (state: {self._state.name})"
            )

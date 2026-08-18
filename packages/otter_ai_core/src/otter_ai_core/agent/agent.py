import asyncio
from collections.abc import AsyncGenerator, Callable

from otter_ai_core.agent_tool import AgentTool
from otter_ai_core.components import TerminatingStream
from otter_ai_core.conversation import SessionMessage

from .agent_loop import AgentLoop, _reject_duplicate_tool_names
from .hooks import AgentHooks, AgentLoopHooks
from .types import (
    AgentEnd,
    AgentLoopEvent,
    AgentModel,
    AgentOptions,
    AgentStart,
    AgentStream,
    AgentTurnEnd,
)


class _AgentStream(TerminatingStream[AgentLoopEvent | AgentStart, AgentEnd]):
    terminal_event_type = AgentEnd

    def __init__(self, loop: AgentLoop, settle: Callable[[], None]) -> None:
        self._loop = loop
        self._settle = settle

    async def _iterate_source(
        self,
    ) -> AsyncGenerator[AgentLoopEvent | AgentStart | AgentEnd, None]:
        try:
            yield AgentStart()
            turns: list[AgentTurnEnd] = []
            messages: list[SessionMessage] = []
            async for event in self._loop:
                if isinstance(event, AgentTurnEnd):
                    turns.append(event)
                    messages.extend(event.messages)
                yield event
            yield AgentEnd(messages=messages, turns=turns, termination=turns[-1].termination)
        finally:
            # fires on terminal event, propagated error, and early closure alike
            self._settle()


class Agent:
    def __init__(
        self,
        model: AgentModel,
        tools: list[AgentTool],
        hooks: AgentHooks | None = None,
        options: AgentOptions | None = None,
    ) -> None:
        self._model = model
        self._tools = list(tools)
        self._hooks = hooks
        self._options = options or AgentOptions()
        _reject_duplicate_tool_names(self._tools)
        self._active_loop: AgentLoop | None = None
        self._idle = asyncio.Event()
        self._idle.set()

    def steer(self, text: str) -> None:
        self._require_active("steer").steer(text)

    def follow_up(self, text: str) -> None:
        self._require_active("follow_up").follow_up(text)

    def prompt(self, text: str) -> AgentStream:
        if self._active_loop is not None:
            raise RuntimeError("cannot prompt while an agent run is active")
        loop = AgentLoop(
            self._model,
            tools=self._tools,
            options=self._options.agent_loop_options,
            hooks=self._to_loop_hooks(),
        )
        loop.follow_up(text)
        self._active_loop = loop
        self._idle.clear()
        return _AgentStream(loop, self._settle)

    def is_idle(self) -> bool:
        return self._active_loop is None

    async def wait_for_idle(self) -> None:
        await self._idle.wait()

    def _require_active(self, action: str) -> AgentLoop:
        if self._active_loop is None:
            raise RuntimeError(f"cannot {action} while the agent is idle")
        return self._active_loop

    def _to_loop_hooks(self) -> AgentLoopHooks | None:
        if self._hooks is None:
            return None
        return AgentLoopHooks(
            before_tool_call=self._hooks.before_tool_call,
            tool_result=self._hooks.tool_result,
        )

    def _settle(self) -> None:
        self._active_loop = None
        self._idle.set()

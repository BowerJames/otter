import asyncio
from collections.abc import AsyncGenerator, Callable

from otter_ai_core.components import TerminatingStream
from otter_ai_core.types import SessionMessage

from .agent_loop import AgentLoop, _reject_duplicate_tool_names
from .agent_tool.interface import AgentTool
from .hooks import AgentHooks, AgentLoopHooks
from .model.interface import Model
from .types import (
    AgentEnd,
    AgentLoopEvent,
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
    """Drives a chat model through tool-calling runs, one run at a time.

    Each run is started with `prompt` and consumed as an event stream that
    ends with an AgentEnd terminal event. The model, tools, hooks, and
    options given at construction apply to every run for the agent's
    lifetime."""

    def __init__(
        self,
        model: Model,
        tools: list[AgentTool],
        hooks: AgentHooks | None = None,
        options: AgentOptions | None = None,
    ) -> None:
        """Constructs the agent from the given model, tools, hooks, and
        options.

        `tools` is copied, so later changes to the passed list do not affect
        the agent. Tool names must be unique; duplicates raise ValueError
        naming the duplicated names. `hooks` and `options` default to empty
        hooks and default options when omitted."""
        self._model = model
        self._tools = list(tools)
        self._hooks = hooks
        self._options = options or AgentOptions()
        _reject_duplicate_tool_names(self._tools)
        self._active_loop: AgentLoop | None = None
        self._idle = asyncio.Event()
        self._idle.set()

    def steer(self, text: str) -> None:
        """Delivers `text` to the active run as guidance for the model,
        taking effect ahead of the run's next generation.

        Raises RuntimeError when the agent is idle. The delivered text is
        observable in the run's stream: it is added as a user message that
        precedes the next assistant message."""
        self._require_active("steer").steer(text)

    def follow_up(self, text: str) -> None:
        """Delivers `text` to the active run to be handled as its next user
        message once the current turn ends.

        Raises RuntimeError when the agent is idle. The delivered text is
        observable in the run's stream as the user message that starts the
        run's next turn."""
        self._require_active("follow_up").follow_up(text)

    def prompt(self, text: str) -> AgentStream:
        """Starts a run whose first user message is `text`, and returns the
        run's event stream.

        Raises RuntimeError while another run is active. The stream yields an
        AgentStart event, then the run's events, and ends with an AgentEnd
        terminal event. The agent remains busy until the stream ends — by
        its terminal event, by a raised error, or by the consumer stopping
        early — after which a new run may be started."""
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
        """Returns whether the agent has no active run.

        True exactly when a new run may be started with `prompt`."""
        return self._active_loop is None

    async def wait_for_idle(self) -> None:
        """Waits until the agent is idle.

        Returns immediately when the agent is already idle. The active
        run's stream ends before the wait completes, however it ends."""
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

from collections.abc import AsyncIterator, Iterable

from otter_ai_core.agent_tool import AgentTool
from otter_ai_core.model import Model

from .hooks import AgentLoopHooks
from .types import AgentLoopOptions, AgentLoopTurn


class AgentLoopExhausted(RuntimeError): ...


class AgentLoopStranded(RuntimeError): ...


class AgentLoop:
    def __init__(
        self,
        model: Model,
        tools: Iterable[AgentTool] = (),
        options: AgentLoopOptions | None = None,
        hooks: AgentLoopHooks | None = None,
    ) -> None:
        self._model = model
        self._tools = tuple(tools)
        self._options = options or AgentLoopOptions()
        self._hooks = hooks or AgentLoopHooks()
        self._iteration_claimed = False

    def follow_up(self, text: str) -> None:
        raise NotImplementedError

    def steer(self, text: str) -> None:
        raise NotImplementedError

    def __aiter__(self) -> AsyncIterator[AgentLoopTurn]:
        if self._iteration_claimed:
            raise RuntimeError("AgentLoop is single-use; construct a new AgentLoop to run again")
        self._iteration_claimed = True
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[AgentLoopTurn]:
        raise NotImplementedError
        yield  # unreachable: marks _iterate as an async generator

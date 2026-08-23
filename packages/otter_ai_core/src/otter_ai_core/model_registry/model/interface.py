from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Protocol, Self

from otter_ai_core.agent.model import Model
from otter_ai_core.agent_tool import AgentTool


class EnterableModel(Model, Protocol):
    def __aenter__(self) -> Awaitable[Self]: ...

    def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Awaitable[bool | None]: ...


# A ModelFactory yields a fresh, unentered model, bound to the given system
# prompt and tools, whose session can complete at least one generate() and
# accepts a tool result for an arbitrary tool_call_id. Anything a check needs
# to observe through the interface must be arranged by the factory; checks
# receive nothing else.
type ModelFactory = Callable[[str, list[AgentTool]], EnterableModel]

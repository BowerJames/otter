from otter_ai_core.agent_tool import AgentTool

from .hooks import AgentHooks
from .types import AgentModel, AgentOptions, AgentStream


class Agent:
    def __init__(
        self,
        model: AgentModel,
        tools: list[AgentTool],
        hooks: AgentHooks | None = None,
        options: AgentOptions | None = None,
    ) -> None:
        raise NotImplementedError

    def steer(self, text: str) -> None:
        raise NotImplementedError

    def follow_up(self, text: str) -> None:
        raise NotImplementedError

    def prompt(self, text: str) -> AgentStream:
        raise NotImplementedError

    def is_idle(self) -> bool:
        raise NotImplementedError

    async def wait_for_idle(self) -> None:
        raise NotImplementedError

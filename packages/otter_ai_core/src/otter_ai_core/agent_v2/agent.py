from typing import AsyncIterable

from otter_ai_core.abstractions import Model, AgentTool
from otter_ai_core.agent_v2.types import AgentEvents

class Agent:

    def __init__(
            self,
            model: Model,
            tools: list[AgentTool],
        ):
        raise NotImplementedError

    def stream(self) -> AsyncIterable[AgentEvents]:
        raise NotImplementedError

    def cancel_stream(self) -> None:
        raise NotImplementedError

    def prompt(self, text: str) -> None:
        raise NotImplementedError

    def is_idle(self) -> bool:
        raise NotImplementedError

    async def wait_for_idle(self):
        raise NotImplementedError


    

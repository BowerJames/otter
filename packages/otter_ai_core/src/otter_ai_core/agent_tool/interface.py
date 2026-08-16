from typing import Any, Protocol

from pydantic import BaseModel

from .types import AgentToolResult


class AgentTool(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def parameters(self) -> type[BaseModel]: ...

    async def execute(self, arguments: dict[str, Any]) -> AgentToolResult: ...

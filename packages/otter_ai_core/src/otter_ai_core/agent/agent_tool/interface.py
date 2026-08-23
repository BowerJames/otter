from typing import Any, Protocol

from pydantic import BaseModel

from otter_ai_core.types import AgentToolResult


class AgentTool(Protocol):
    """Abstraction over a tool invocable with a mapping of arguments,
    returning a structured result."""

    @property
    def name(self) -> str:
        """Stable identifier for the tool."""
        ...

    @property
    def description(self) -> str:
        """Natural-language account of what the tool does."""
        ...

    @property
    def parameters(self) -> type[BaseModel]:
        """Pydantic model describing the arguments the tool accepts."""
        ...

    async def execute(self, arguments: dict[str, Any]) -> AgentToolResult:
        """Runs the tool with the raw arguments. The returned AgentToolResult
        carries the outcome: is_error marks the result as a failure,
        terminate requests that the caller make no further tool calls."""
        ...

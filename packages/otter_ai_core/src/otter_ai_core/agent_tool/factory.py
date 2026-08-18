from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from .signature import AgentTool
from .types import AgentToolResult


class _CallableAgentTool[TPayload: BaseModel]:
    def __init__(
        self,
        name: str,
        description: str,
        parameters: type[TPayload],
        execute: Callable[[TPayload], Awaitable[AgentToolResult]],
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self._execute = execute

    async def execute(self, arguments: dict[str, Any]) -> AgentToolResult:
        try:
            payload = self.parameters.model_validate(arguments)
        except ValidationError as error:
            return AgentToolResult(text=self._validation_error_text(error), is_error=True)
        return await self._execute(payload)

    def _validation_error_text(self, error: ValidationError) -> str:
        details = "; ".join(
            f"{'.'.join(str(location) for location in detail['loc']) or '(root)'}: {detail['msg']}"
            for detail in error.errors(include_url=False)
        )
        return f"invalid arguments for tool {self.name!r}: {details}"


def create_agent_tool[TPayload: BaseModel](
    name: str,
    description: str,
    parameters: type[TPayload],
    execute: Callable[[TPayload], Awaitable[AgentToolResult]],
) -> AgentTool:
    return _CallableAgentTool[TPayload](name, description, parameters, execute)

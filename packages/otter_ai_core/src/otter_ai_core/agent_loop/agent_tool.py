import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel

from otter_ai_core.context import UserContent


@dataclass(slots=True)
class AgentToolResult[TDetails]:
    result: list[UserContent]
    details: TDetails
    is_error: bool = False
    terminate: bool = False


class AgentTool[TParams: BaseModel, TDetails]:
    name: str
    description: str
    parameters: type[TParams]
    _execute: Callable[
        [str, TParams, asyncio.Event], Awaitable[AgentToolResult[TDetails]]
    ]

    def __init__(
        self,
        name: str,
        description: str,
        parameters: type[TParams],
        execute: Callable[
            [str, TParams, asyncio.Event], Awaitable[AgentToolResult[TDetails]]
        ]
    ) -> None:
        self.name=name
        self.description=description
        self.parameters=parameters
        self._execute=execute

    async def execute(
        self, tool_call_id: str, params: object, signal: asyncio.Event
    ) -> AgentToolResult[TDetails]:
        params_cls = self.parameters
        match params:
            case _ if isinstance(params, params_cls):
                validated_params = params
            case dict():
                validated_params = params_cls.model_validate(params)
            case str():
                validated_params = params_cls.model_validate_json(params)
            case _:
                raise RuntimeError(f"Invalid object passed to tool execution {params}")
        return await self._execute(
            tool_call_id,
            validated_params,
            signal
        )
    
def create_agent_tool[TParams: BaseModel, TDetails](
    name: str,
    description: str,
    parameters: type[TParams],
    execute: Callable[
        [str, TParams, asyncio.Event], Awaitable[AgentToolResult[TDetails]]
    ]
) -> AgentTool[TParams, TDetails]:
    return AgentTool(
        name,
        description,
        parameters,
        execute
    )
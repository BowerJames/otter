import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from otter_ai_core.context import UserContent

TParams = TypeVar("TParams", bound=BaseModel)


@dataclass(slots=True)
class AgentToolResult[TDetails]:
    result: list[UserContent]
    details: TDetails
    is_error: bool = False
    terminate: bool = False


class AgentTool[TParams, TDetails]:
    name: str
    description: str
    parameters: TParams
    _execute: Callable[
        [str, TParams, asyncio.Event], Awaitable[AgentToolResult[TDetails]]
    ]

    async def execute(
        self, tool_call_id: str, params: object, signal: asyncio.Event
    ) -> AgentToolResult[TDetails]:
        raise NotImplementedError("AgentTool.execute not implemented yet")

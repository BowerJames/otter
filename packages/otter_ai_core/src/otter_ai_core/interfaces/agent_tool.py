from __future__ import annotations

import asyncio
from typing import Protocol

from pydantic import BaseModel

from otter_ai_core.agent_loop.agent_tool import AgentToolResult


class AgentTool[TParams: BaseModel, TDetails](Protocol):
    name: str
    description: str
    parameters: type[TParams]

    async def execute(
        self, tool_call_id: str, params: object, signal: asyncio.Event
    ) -> AgentToolResult[TDetails]: ...


__all__ = [
    "AgentTool",
]

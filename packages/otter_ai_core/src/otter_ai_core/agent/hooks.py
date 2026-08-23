from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from otter_ai_core.types import AgentToolResult, ToolCall


class ToolCallDecision(BaseModel):
    action: Literal["run", "deny"]
    reason: str | None = None


type BeforeToolCallHook = Callable[[ToolCall], Awaitable[ToolCallDecision]]
type ToolResultHook = Callable[[ToolCall, AgentToolResult], Awaitable[AgentToolResult]]


@dataclass(frozen=True)
class AgentLoopHooks:
    before_tool_call: BeforeToolCallHook | None = None
    tool_result: ToolResultHook | None = None


@dataclass(frozen=True)
class AgentHooks(AgentLoopHooks): ...

from collections.abc import Awaitable
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from otter_ai_core.agent_tool import AgentToolResult
from otter_ai_core.model import AssistantMessage, ToolResultMessage, UserMessage

type DrainMode = Literal["one-by-one", "all-at-once"]
type SessionMessage = UserMessage | AssistantMessage | ToolResultMessage


class AgentLoopModel(Protocol):
    def add_user_message(self, text: str) -> Awaitable[UserMessage]: ...

    def add_tool_result_message(
        self, tool_call_id: str, text: str
    ) -> Awaitable[ToolResultMessage]: ...

    def generate(self) -> Awaitable[AssistantMessage]: ...


class AgentLoopOptions(BaseModel):
    follow_up_drain: DrainMode = "one-by-one"
    steering_drain: DrainMode = "all-at-once"
    max_generations: int | None = Field(default=None, ge=1)


class ToolExecution(BaseModel):
    tool_call_id: str
    tool_name: str
    result: AgentToolResult


class AgentLoopTurn(BaseModel):
    messages: list[SessionMessage]
    assistant_message: AssistantMessage
    tool_executions: list[ToolExecution]
    generations: int
    termination: Literal["final_response", "tool_terminated"]

from collections.abc import Awaitable
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from otter_ai_core.conversation import (
    AssistantMessage,
    SessionMessage,
    ToolResultMessage,
    UserMessage,
)

type DrainMode = Literal["one-by-one", "all-at-once"]


class AgentModel(Protocol):
    def add_user_message(self, text: str) -> Awaitable[UserMessage]: ...

    def add_tool_result_message(
        self, tool_call_id: str, text: str
    ) -> Awaitable[ToolResultMessage]: ...

    def generate(self) -> Awaitable[AssistantMessage]: ...


class AgentLoopOptions(BaseModel):
    follow_up_drain: DrainMode = "one-by-one"
    steering_drain: DrainMode = "all-at-once"
    max_generations: int | None = Field(default=None, ge=1)


class AgentTurnStart(BaseModel):
    pass


class AgentTurnEnd(BaseModel):
    messages: list[SessionMessage]
    user_messages: list[UserMessage]
    assistant_message: AssistantMessage
    tool_result_messages: list[ToolResultMessage]
    generations: int
    termination: Literal["final_response", "tool_terminated"]


type AgentLoopEvent = SessionMessage | AgentTurnStart | AgentTurnEnd

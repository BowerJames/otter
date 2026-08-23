from typing import Literal

from pydantic import BaseModel, Field

from otter_ai_core.components import TerminatingStream
from otter_ai_core.types import (
    AssistantMessage,
    SessionMessage,
    ToolResultMessage,
    UserMessage,
)

type DrainMode = Literal["one-by-one", "all-at-once"]


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


class AgentOptions(BaseModel):
    agent_loop_options: AgentLoopOptions = Field(default_factory=AgentLoopOptions)


class AgentStart(BaseModel):
    pass


class AgentEnd(BaseModel):
    messages: list[SessionMessage]
    turns: list[AgentTurnEnd]
    termination: Literal["final_response", "tool_terminated"]


type AgentEvent = AgentLoopEvent | AgentStart | AgentEnd
type AgentStream = TerminatingStream[AgentLoopEvent | AgentStart, AgentEnd]

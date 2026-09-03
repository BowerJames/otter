from pydantic import BaseModel
from typing import Literal

from otter_ai_core.types import (
    AssistantMessage,
    SessionMessage,
    ToolResultMessage,
    UserMessage,
)
from otter_ai_core.components import TerminatingStream

class _Event(BaseModel):
    type: str
    id: str

class _Iteration(BaseModel):
    user_messages = list[UserMessage]
    assistant_message: AssistantMessage
    tool_result_messages = list[ToolResultMessage] | None

class AgentTurnStartEvent(_Event):
    type: Literal["agent_turn_start"] = "agent_turn_start"

class AgentIterationStartEvent(BaseModel):
    type: Literal["agent_iteration_start"]

class AgentSessionMessageEvent(_Event):
    type: Literal["session_message"] = "session_message"

    message: SessionMessage

class AgentIterationEndEvent(_Event):
    type: Literal["agent_iteration_end"]

    user_messages = list[UserMessage]
    assistant_message: AssistantMessage
    tool_result_messages = list[ToolResultMessage] | None
    termination: Literal["final_response", "tool_response", "error"]

class AgentTurnEndEvent(_Event):
    type: Literal["agent_turn_end"] = "agent_turn_end"

    iterations: list[_Iteration]
    termination: Literal["final_response", "error"]




type AgentEvents = AgentTurnStartEvent | AgentIterationStartEvent | AgentSessionMessageEvent | AgentIterationEndEvent | AgentTurnEndEvent
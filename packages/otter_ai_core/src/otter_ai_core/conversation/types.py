from typing import Any, Literal

from pydantic import BaseModel


class TextContent(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ThinkingContent(BaseModel):
    type: Literal["thinking"] = "thinking"
    text: str


class ToolCall(BaseModel):
    id: str
    tool_name: str
    parameters: dict[str, Any]


class UserMessage(BaseModel):
    id: str
    role: Literal["user"] = "user"
    content: list[TextContent]


class ToolResultMessage(BaseModel):
    id: str
    tool_call_id: str
    role: Literal["tool_result"] = "tool_result"
    content: list[TextContent]


class AssistantMessage(BaseModel):
    id: str
    role: Literal["assistant"] = "assistant"
    content: list[ThinkingContent | TextContent]
    tool_calls: list[ToolCall]
    stop_reason: Literal["final_response", "tool_call"]


type SessionMessage = UserMessage | AssistantMessage | ToolResultMessage

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from otter_ai_core.data_models.context.content import AssistantContent, ToolCall, UserContent
from otter_ai_core.data_models.context.diagnostics import AssistantMessageDiagnostic
from otter_ai_core.data_models.context.role import Role
from otter_ai_core.data_models.context.usage import Usage


class StopReason(StrEnum):
    Stop = "stop"
    Length = "length"
    ToolUse = "tool_use"
    Error = "error"
    Aborted = "aborted"


class UserMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.User]
    content: str | list[UserContent]
    #: Unix timestamp in milliseconds.
    timestamp: int


class AssistantMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.Assistant]
    content: list[AssistantContent]
    api: str
    provider: str
    model: str
    #: Concrete model id when the upstream differs from the one requested
    #: (e.g. an ``"auto"`` routing model resolving to a specific provider model).
    response_model: str | None = None
    #: Provider-specific response/message id when the upstream exposes one.
    response_id: str | None = None
    diagnostics: list[AssistantMessageDiagnostic] | None = None
    usage: Usage
    #: Why generation stopped. ``None`` only while the message is in flight
    #: (a partial snapshot); a terminal message always carries a value.
    stop_reason: StopReason | None
    error_message: str | None = None
    #: Unix timestamp in milliseconds.
    timestamp: int

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [content_part for content_part in self.content if isinstance(content_part, ToolCall)]


class ToolResultMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal[Role.ToolResult]
    tool_call_id: str
    tool_name: str
    content: list[UserContent]
    #: Open extension point for tool-specific metadata (arbitrary JSON value).
    details: Any | None = None
    is_error: bool
    #: Unix timestamp in milliseconds.
    timestamp: int


#: Discriminated union of all message roles.
Message = Annotated[UserMessage | AssistantMessage | ToolResultMessage, Field(discriminator="role")]

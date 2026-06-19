"""The three message roles of a conversation.

A :data:`Message` is a discriminated union over ``role`` with members
:class:`UserMessage`, :class:`AssistantMessage`, and
:class:`ToolResultMessage`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from otter_ai.content import AssistantContent, UserContent
from otter_ai.diagnostics import AssistantMessageDiagnostic
from otter_ai.types import Api, Provider, StopReason
from otter_ai.usage import Usage


class UserMessage(BaseModel):
    """A user-authored message.

    ``content`` is either a plain string (convenience) or a list of structured
    content blocks (required for multimodal input).
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["user"]
    content: str | list[UserContent]
    #: Unix timestamp in milliseconds.
    timestamp: int


class AssistantMessage(BaseModel):
    """A model-authored message.

    Provenance fields (``api``/``provider``/``model``/``response_model``/
    ``response_id``) and accounting (``usage``/``stop_reason``/``error_message``)
    are stored inertly — otter never interprets them, but preserves them so a
    context can be replayed elsewhere.
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"]
    content: list[AssistantContent]
    api: Api
    provider: Provider
    model: str
    #: Concrete model id when the upstream differs from the one requested
    #: (e.g. an ``"auto"`` routing model resolving to a specific provider model).
    response_model: str | None = None
    #: Provider-specific response/message id when the upstream exposes one.
    response_id: str | None = None
    diagnostics: list[AssistantMessageDiagnostic] | None = None
    usage: Usage
    stop_reason: StopReason
    error_message: str | None = None
    #: Unix timestamp in milliseconds.
    timestamp: int


class ToolResultMessage(BaseModel):
    """The result of a tool call, fed back to the model.

    Unlike :class:`UserMessage`, ``content`` is always a list of structured
    blocks (no plain-string shorthand).
    """

    model_config = ConfigDict(extra="forbid")

    role: Literal["tool_result"]
    tool_call_id: str
    tool_name: str
    content: list[UserContent]
    #: Open extension point for tool-specific metadata (arbitrary JSON value).
    details: Any | None = None
    is_error: bool
    #: Unix timestamp in milliseconds.
    timestamp: int


#: Discriminated union of all message roles.
Message = Annotated[
    UserMessage | AssistantMessage | ToolResultMessage, Field(discriminator="role")
]

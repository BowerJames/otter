from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from otter_ai_core.context.messages import (
    AssistantMessage,
    Message,
    ToolResultMessage,
    UserMessage,
)


class BaseContextItem[TMsg: BaseModel](BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    message: TMsg


class UserContextItem(BaseContextItem[UserMessage]):
    pass


class AssistantContextItem(BaseContextItem[AssistantMessage]):
    pass


class ToolResultContextItem(BaseContextItem[ToolResultMessage]):
    pass


#: Union of all context item roles. The inner ``message`` is itself a
#: ``role``-discriminated union (see :data:`otter_ai_core.context.Message`),
#: so members are distinguished by their ``message``'s ``role``.
ContextItem = UserContextItem | AssistantContextItem | ToolResultContextItem


def context_item(message: Message, id: str) -> ContextItem:
    if isinstance(message, UserMessage):
        return UserContextItem(id=id, message=message)
    if isinstance(message, AssistantMessage):
        return AssistantContextItem(id=id, message=message)
    if isinstance(message, ToolResultMessage):
        return ToolResultContextItem(id=id, message=message)
    raise ValueError(f"Unknown message role: {message.role!r}")

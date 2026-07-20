"""Context items: messages tagged with an ``id`` for placement in a Context.

A :data:`ContextItem` is a union of :class:`UserContextItem`,
:class:`AssistantContextItem`, and :class:`ToolResultContextItem`. Each is a
subclass of the generic :class:`BaseContextItem` ``[TMsg]`` that *wraps* a
message (an ``id`` plus a nested ``message`` attribute) rather than inheriting
the message's fields — so a context item is shaped ``{id, message}``. Build one
with the :func:`context_item` dispatcher or the concrete subclass constructor
(e.g. ``UserContextItem(id=..., message=...)``).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from otter_ai_core.context.messages import (
    AssistantMessage,
    Message,
    ToolResultMessage,
    UserMessage,
)


class BaseContextItem[TMsg: BaseModel](BaseModel):
    """Base for all context items: an ``id`` plus the wrapped ``message``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    message: TMsg


class UserContextItem(BaseContextItem[UserMessage]):
    """A user message context item."""


class AssistantContextItem(BaseContextItem[AssistantMessage]):
    """An assistant message context item."""


class ToolResultContextItem(BaseContextItem[ToolResultMessage]):
    """A tool result message context item."""


#: Union of all context item roles. The inner ``message`` is itself a
#: ``role``-discriminated union (see :data:`otter_ai_core.context.Message`),
#: so members are distinguished by their ``message``'s ``role``.
ContextItem = UserContextItem | AssistantContextItem | ToolResultContextItem


def context_item(message: Message, id: str) -> ContextItem:
    """Build a :data:`ContextItem` from a message, dispatching on ``role``.

    Lets callers build the matching item subclass from a :data:`Message`
    without sniffing ``role`` themselves.
    """
    if isinstance(message, UserMessage):
        return UserContextItem(id=id, message=message)
    if isinstance(message, AssistantMessage):
        return AssistantContextItem(id=id, message=message)
    if isinstance(message, ToolResultMessage):
        return ToolResultContextItem(id=id, message=message)
    raise ValueError(f"Unknown message role: {message.role!r}")

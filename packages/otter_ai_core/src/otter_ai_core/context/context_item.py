"""Context items: messages tagged with an ``id`` for placement in a Context.

A :data:`ContextItem` is a discriminated union (on ``role``) of the three
subclasses below. Each subclass inherits a message type's fields directly via
multiple inheritance, so a context item *is* the message plus an ``id`` — there
is no nested ``message`` attribute. Use :meth:`BaseContextItem.to_message` /
:meth:`BaseContextItem.from_message` (or the :func:`context_item` dispatcher)
to convert between the two shapes.
"""

from __future__ import annotations

from typing import Annotated, ClassVar, Self, cast

from pydantic import BaseModel, Field

from otter_ai_core.context.messages import (
    AssistantMessage,
    Message,
    ToolResultMessage,
    UserMessage,
)


class BaseContextItem[MsgT: BaseModel](BaseModel):
    """Base for all context items.

    A context item is a message that can be added to the context. It can be a
    user message, an assistant message, or a tool result message. Subclasses
    additionally inherit the fields of the corresponding message type.

    ``to_message`` / ``from_message`` are defined once here and inherited by
    every subclass; each subclass only contributes ``_MESSAGE_CLS``.
    """

    id: str

    #: The message type this item wraps. Set on each concrete subclass.
    _MESSAGE_CLS: ClassVar[type[BaseModel]]

    def to_message(self) -> MsgT:
        """Return the underlying message (dropping the ``id`` field)."""
        message_cls = type(self)._MESSAGE_CLS
        fields = set(message_cls.model_fields)
        return cast(MsgT, message_cls.model_validate(self.model_dump(include=fields)))

    @classmethod
    def from_message(cls, message: MsgT, id: str) -> Self:
        """Build a context item of this type from a message and an ``id``."""
        return cls(**{**message.model_dump(), "id": id})


class UserContextItem(BaseContextItem[UserMessage], UserMessage):
    """A user message context item."""

    _MESSAGE_CLS = UserMessage


class AssistantContextItem(BaseContextItem[AssistantMessage], AssistantMessage):
    """An assistant message context item."""

    _MESSAGE_CLS = AssistantMessage


class ToolResultContextItem(BaseContextItem[ToolResultMessage], ToolResultMessage):
    """A tool result message context item."""

    _MESSAGE_CLS = ToolResultMessage


#: Discriminated union of all context item roles.
ContextItem = Annotated[
    UserContextItem | AssistantContextItem | ToolResultContextItem,
    Field(discriminator="role"),
]


def context_item(message: Message, id: str) -> ContextItem:
    """Build a :data:`ContextItem` from a message, dispatching on ``role``.

    Lets callers migrate the pre-refactor idiom
    ``ContextItem(id=..., message=...)`` near-verbatim to
    ``context_item(message=..., id=...)`` without splatting message fields.
    """
    if isinstance(message, UserMessage):
        return UserContextItem.from_message(message, id=id)
    if isinstance(message, AssistantMessage):
        return AssistantContextItem.from_message(message, id=id)
    if isinstance(message, ToolResultMessage):
        return ToolResultContextItem.from_message(message, id=id)
    raise ValueError(f"Unknown message role: {message.role!r}")

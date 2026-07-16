"""Shared typing primitives for discriminated event families."""

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel


class EventLike(Protocol):
    """Structural view required by the generic event bus.

    The discriminator is exposed as a read-only property so concrete event
    variants may safely narrow it to a literal enum member. Event objects do
    not need to inherit from this protocol or from :class:`Event`.
    """

    @property
    def type(self) -> StrEnum: ...


class Event[TEventType: StrEnum](BaseModel):
    """Pydantic event base tying a model family to its discriminator enum.

    Concrete variants narrow ``type`` to a literal member. The generic base
    lets static checking reject a variant that accidentally uses a member from
    a different enum family; the bus itself relies only on :class:`EventLike`.
    """

    type: TEventType

"""Shared typing primitives for discriminated event families."""

from enum import StrEnum

from pydantic import BaseModel


class Event[TEventType: StrEnum](BaseModel):
    """Pydantic event base tying a model family to its discriminator enum.

    Concrete variants narrow ``type`` to a literal member. The generic base
    lets static checking reject a variant that accidentally uses a member from
    a different enum family. (The :class:`~otter_ai_core.bus.Bus` no longer
    routes on ``type`` — it is descriptor-keyed — but the discriminator is still
    used by the connection protocol and by consumers that ``match`` on the
    event union.)
    """

    type: TEventType

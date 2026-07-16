"""Model-controller specialization of the generic typed event bus.

:class:`ModelBus` preserves the public zero-argument model-controller API while
all queueing, dispatch, handler isolation, and lifecycle behavior lives in
:class:`otter_ai_core.bus.Bus`.
"""

from collections.abc import Awaitable, Callable

from otter_ai_core.bus import Bus
from otter_ai_core.model_connection import ServerContextEvent, ServerContextEventType

#: An async subscriber invoked for each matching server event.
Handler = Callable[[ServerContextEvent], Awaitable[None]]


class ModelBus(Bus[ServerContextEventType, ServerContextEvent]):
    """A generic bus specialized for server-to-client model events."""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__(ServerContextEventType)

import asyncio
from typing import TYPE_CHECKING, Callable, Awaitable, Any

from .phase import Phase
from .state_machine import ModelStateMachine
from .bus import ModelSessionBus
from .events import SessionEventTypes

from otter_ai_core.model_connection import (
    ModelConnection,
    ServerEvent,
    ServerEventTypes,
    ResponseCreate,
    ContextItemAddEvent,
    AbortResponseEvent
)

if TYPE_CHECKING:

    from otter_ai_core.context.context_item import ContextItem



class ModelSession:
    _state_machine: ModelStateMachine
    _conn: ModelConnection
    _bus: ModelSessionBus
    _task: asyncio.Task

    def __init__(self, conn: ModelConnection):
        self._state_machine = ModelStateMachine()
        self._conn = conn
        self._bus = ModelSessionBus()
        self._task = asyncio.create_task(self._receive_events())

    async def _receive_events(self):
        try:
            async for event in self._conn:
                match event.type:
                    case (
                        ServerEventTypes.ResponseDone
                        | ServerEventTypes.ResponseAborted
                        | ServerEventTypes.ResponseError
                    ):
                        self._state_machine.set_idle()
                self._bus.publish(event)
        finally:
            self._state_machine.close_connection()
            self._bus.publish(None)

    def create_response(self):
        if not self._state_machine.running:
            return
        match self._state_machine.phase:
            case Phase.IDLE:
                self._state_machine.set_working()
                self._conn.send(ResponseCreate())

    def add_context_item(self, item: ContextItem):
        if not self._state_machine.running:
            return
        self._conn.send(ContextItemAddEvent(item=item))

    def abort_response(self):
        if not self._state_machine.running:
            return
        match self._state_machine.phase:
            case Phase.WORKING:
                self._state_machine.set_aborting()
                self._conn.send(AbortResponseEvent()) 
            case _:
                pass

    def close(self):
        if not self._state_machine.running:
            return
        self._state_machine.close_connection()
        match self._state_machine.phase:
            case Phase.WORKING:
                self._state_machine.set_aborting()
                self._conn.send(AbortResponseEvent())
            case _:
                pass
        self._conn.close()

    def on(self, event: SessionEventTypes, handler: Callable[[Any],Awaitable[None]]) -> Callable[[],None]:
        return self._bus.subscribe(event, handler)
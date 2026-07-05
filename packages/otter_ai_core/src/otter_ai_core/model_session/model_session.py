import asyncio
from collections.abc import Callable

from otter_ai_core.context.context_item import ContextItem
from otter_ai_core.hook import Hook
from otter_ai_core.model_connection import (
    AbortResponseEvent,
    ContextItemAddEvent,
    ModelConnection,
    ResponseCreate,
    ServerEventTypes,
)

from .bus import ModelSessionBus
from .events import SessionClosedEvent, SessionEvent, SessionEventTypes
from .phase import Phase
from .reduce import reduce_server_event
from .state_machine import ModelStateMachine


class ModelSession:
    _state_machine: ModelStateMachine
    _conn: ModelConnection
    _bus: ModelSessionBus
    _task: asyncio.Task[None]

    def __init__(self, conn: ModelConnection) -> None:
        self._state_machine = ModelStateMachine()
        self._conn = conn
        self._bus = ModelSessionBus()
        self._task = asyncio.create_task(self._receive_events())

    async def _receive_events(self) -> None:
        try:
            async for event in self._conn:
                match event.type:
                    case (
                        ServerEventTypes.ResponseDone
                        | ServerEventTypes.ResponseAborted
                        | ServerEventTypes.ResponseError
                    ):
                        self._state_machine.set_idle()
                for session_event in reduce_server_event(event):
                    self._bus.publish(session_event)
        finally:
            self._state_machine.close_connection()
            self._bus.publish(SessionClosedEvent(type=SessionEventTypes.SessionClosed))
            self._bus.publish(None)

    def create_response(self) -> None:
        if not self._state_machine.running:
            return
        match self._state_machine.phase:
            case Phase.IDLE:
                self._state_machine.set_working()
                self._conn.send(ResponseCreate())

    def add_context_item(self, item: ContextItem) -> None:
        if not self._state_machine.running:
            return
        self._conn.send(ContextItemAddEvent(item=item))

    def abort_response(self) -> None:
        if not self._state_machine.running:
            return
        match self._state_machine.phase:
            case Phase.WORKING:
                self._state_machine.set_aborting()
                self._conn.send(AbortResponseEvent())
            case _:
                pass

    def close(self) -> None:
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

    def on(
        self,
        event: SessionEventTypes,
        handler: Hook[SessionEvent, None],
    ) -> Callable[[], None]:
        return self._bus.subscribe(event, handler)

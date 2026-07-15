import asyncio
from typing import Callable

from otter_ai_core.stream import StreamClient, StreamBackend, StreamPair, create_stream
from otter_ai_core.model_controller import ModelController
from otter_ai_core.model_connection import ServerContextEventType, ServerContextEvent
from otter_ai_core.model_controller.bus import Handler


class ModelControllerStreamProducer:
    _controller: ModelController
    _backend: StreamBackend[ServerContextEvent]
    _task: asyncio.Task[None]
    _unsubscribers: list[Callable[[], None]]

    def __init__(self, controller: ModelController,  backend: StreamBackend[ServerContextEvent]) -> None:
        self._controller=controller
        self._backend=backend
        self._task = asyncio.create_task(self._run())
        self._unsubscribers = self._subscribe()


    def _subscribe(self) -> list[Callable[[],None]]:
        unsubscribers = []
        for type in ServerContextEventType:
            unsubscribers.append(
                    self._controller.on(
                    type,
                    lambda x: self._handler(x)
                )
            )
        return unsubscribers
        
    
    def _unsubscribe(self) -> None:
        while len(self._unsubscribers) > 0:
            unsubscriber = self._unsubscribers.pop()
            unsubscriber()

    async def _run(self) -> None:
        try:
            wait_for_abort = asyncio.create_task(self._backend.abort_signal.wait())
            wait_for_idle = asyncio.create_task(self._controller.wait_for_idle())
            done, _ = await asyncio.wait(
                [
                    wait_for_abort,
                    wait_for_idle
                ],
                return_when=asyncio.FIRST_COMPLETED
            )
            if wait_for_abort in done:
                self._controller.abort()
                await wait_for_idle
            else:
                wait_for_abort.cancel()
            return
        finally:
            self._unsubscribe()

    async def _handler(self, event: ServerContextEvent) -> None:
        match event.type:
            case ServerContextEventType.RESPONSE_DONE:
                self._backend.push(event)
                self._backend.end()
            case _:
                self._backend.push(event)

def create_model_controller_stream(controller: ModelController) -> StreamClient[ServerContextEvent]:
    stream_pair: StreamPair[ServerContextEvent] = create_stream()
    _ = ModelControllerStreamProducer(controller, stream_pair.backend)
    return stream_pair.client
    
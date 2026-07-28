import asyncio
from collections.abc import Callable

from otter_ai_core.interfaces import ModelController
from otter_ai_core.model_connection import ResponseDone, ServerContextEvent, ServerContextEventType
from otter_ai_core.stream import StreamBackend, StreamClient, StreamPair, create_stream_pair


class ModelControllerStreamProducer:
    _controller: ModelController
    _backend: StreamBackend[ServerContextEvent]
    _task: asyncio.Task[None]
    _unsubscribers: list[Callable[[], None]]

    def __init__(
        self, controller: ModelController, backend: StreamBackend[ServerContextEvent]
    ) -> None:
        self._controller = controller
        self._backend = backend
        self._task = asyncio.create_task(self._run())
        self._unsubscribers = self._subscribe()

    def _subscribe(self) -> list[Callable[[], None]]:
        # Subscribe the single pass-through handler to every controller event
        # type; the public ``on`` accepts the full ``ServerContextEvent`` union,
        # which the handler narrows.
        unsubscribers = []
        for event_type in ServerContextEventType:
            unsubscribers.append(self._controller.on(event_type, self._handler))
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
                [wait_for_abort, wait_for_idle], return_when=asyncio.FIRST_COMPLETED
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
        self._backend.push(event)
        if isinstance(event, ResponseDone):
            self._backend.end()


def create_model_controller_stream(controller: ModelController) -> StreamClient[ServerContextEvent]:
    stream_pair: StreamPair[ServerContextEvent] = create_stream_pair()
    _ = ModelControllerStreamProducer(controller, stream_pair.backend)
    return stream_pair.client

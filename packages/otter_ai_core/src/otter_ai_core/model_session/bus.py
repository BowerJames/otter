import asyncio
import logging
from typing import Awaitable, Any, Callable

from .events import SessionEvent, SessionEventTypes

class ModelSessionBus:
    _queue: asyncio.Queue[SessionEvent]
    _running: bool
    _task = asyncio.Task
    _handlers = dict[SessionEventTypes, list[Callable[[Any],Awaitable[None]]]]

    def __init__(self):
        self._queue = asyncio.Queue[SessionEvent]()
        self._handlers = {
            value: [] for value in SessionEventTypes
        }
        self._running = True
        self._task = asyncio.create_task(self._run())

    def publish(self, event: SessionEvent | None):
        match event:
            case None:
                self._running=False
            case _:
                self._queue.put_nowait(event)
        

    def subscribe(self, event: SessionEventTypes, handler: Callable[[Any],Awaitable[None]]) -> Callable[[],None]:
        self._handlers[event].append(handler)
        return lambda: self._unsubscribe(event,handler)

    def _unsubscribe(self, event: SessionEventTypes, handler: Callable[[Any],Awaitable[None]]):
        self._handlers[event].remove(handler)

    async def _run(self):
        while self._running:
            event = await self._queue.get()
            await self._handle(event)
        while not self._queue.empty():
            event = self._queue.get_nowait()
            await self._handle(event)
        
    async def _handle(self, event: SessionEvent):
        for handler in self._handlers[event.type]:
            try:
                await handler(event)
            except Exception as e:
                logging.error(f"Error in ModelSessionBus in handler {handler} with event {event}: {e}")




        
    

    


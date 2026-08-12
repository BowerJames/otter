from __future__ import annotations

import asyncio
from typing import Self

from otter_ai_core.data_models.events import ServerContextEvent
from otter_ai_core.interfaces.roles.model_connection import ModelConnection


class _RecordingModelConnection(ModelConnection):
    def __init__(self, idle: bool = True, auto_end: bool = False) -> None:
        self._queue: asyncio.Queue[ServerContextEvent | None] = asyncio.Queue()
        self._idle: bool = idle
        self._auto_end: bool = auto_end
        self._ended: bool = False
        self.user_messages: list[str] = []
        self.tool_results: list[tuple[str, str, object]] = []
        self.generate_calls: int = 0
        self.abort_calls: int = 0

    def add_user_message(self, text: str) -> None:
        self.user_messages.append(text)

    def add_tool_result(self, tool_call_id: str, tool_name: str, result: object) -> None:
        self.tool_results.append((tool_call_id, tool_name, result))

    def generate(self) -> None:
        self.generate_calls += 1

    def abort(self) -> None:
        self.abort_calls += 1

    def end(self) -> None:
        if self._auto_end and not self._ended:
            self._queue.put_nowait(None)
        self._ended = True

    def feed(self, event: ServerContextEvent) -> None:
        self._queue.put_nowait(event)

    def trigger_end(self) -> None:
        if self._auto_end:
            raise RuntimeError("trigger_end() cannot be used when auto_end=True")
        if not self._ended:
            raise RuntimeError("end() must be called before trigger_end()")
        self._queue.put_nowait(None)

    def is_idle(self) -> bool:
        return self._idle

    async def wait_for_idle(self) -> None:
        return

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> ServerContextEvent:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item

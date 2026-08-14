from __future__ import annotations

import asyncio
import time
import uuid
from typing import Self

from otter_ai_core.data_models.context import (
    ContentType,
    Role,
    TextContent,
    UserContextItem,
    UserMessage,
)
from otter_ai_core.data_models.events import ServerContextEvent, UserItemAdded
from otter_ai_core.interfaces.roles.model_connection import ModelConnection


class FakeModelConnection(ModelConnection):
    def __init__(
        self,
        idle: bool = True,
        auto_end: bool = False,
        auto_add_user_item: bool = False,
    ) -> None:
        self._queue: asyncio.Queue[ServerContextEvent | None] = asyncio.Queue()
        self._idle: bool = idle
        self._auto_end: bool = auto_end
        self._auto_add_user_item: bool = auto_add_user_item
        self._ended: bool = False

    def add_user_message(self, text: str) -> None:
        if not self._auto_add_user_item:
            return
        self._queue.put_nowait(self._user_item_added(text))

    def confirm_user_message(self, text: str) -> None:
        if self._auto_add_user_item:
            raise RuntimeError("confirm_user_message() cannot be used when auto_add_user_item=True")
        self._queue.put_nowait(self._user_item_added(text))

    def add_tool_result(self, tool_call_id: str, tool_name: str, result: object) -> None:
        raise NotImplementedError

    def generate(self) -> None:
        raise NotImplementedError

    def abort(self) -> None:
        raise NotImplementedError

    def end(self) -> None:
        if self._auto_end and not self._ended:
            self._queue.put_nowait(None)
        self._ended = True

    def trigger_end(self) -> None:
        if self._auto_end:
            raise RuntimeError("trigger_end() cannot be used when auto_end=True")
        if not self._ended:
            raise RuntimeError("end() must be called before trigger_end()")
        self._queue.put_nowait(None)

    def is_idle(self) -> bool:
        return self._idle

    @staticmethod
    def _user_item_added(text: str) -> UserItemAdded:
        return UserItemAdded(
            item=UserContextItem(
                id=uuid.uuid4().hex,
                message=UserMessage(
                    role=Role.User,
                    content=[TextContent(type=ContentType.Text, text=text)],
                    timestamp=int(time.time() * 1000),
                ),
            )
        )

    async def wait_for_idle(self) -> None:
        raise NotImplementedError

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> ServerContextEvent:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item

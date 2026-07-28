from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from otter_ai_core.context import (
    AssistantContextItem,
    ToolResultContextItem,
    UserContextItem,
)
from otter_ai_core.model_connection import (
    BranchMoved,
    CompactionDone,
    InputEvent,
    ServerContextEvent,
    ServerContextEventType,
)


class ModelController(Protocol):
    def is_idle(self) -> bool: ...

    async def wait_for_idle(self) -> None: ...

    def on(
        self,
        event: ServerContextEventType,
        handler: Callable[[ServerContextEvent], Awaitable[None]],
    ) -> Callable[[], None]: ...

    async def add_message(self, message: InputEvent) -> UserContextItem | ToolResultContextItem: ...

    async def generate(self) -> AssistantContextItem: ...

    async def compact(
        self,
        *,
        first_kept_item_id: str | None = None,
        custom_instructions: str | None = None,
        summary: str | None = None,
    ) -> CompactionDone: ...

    async def branch(self, at_item_id: str, *, summary: str | None = None) -> BranchMoved: ...

    def abort(self) -> None: ...

    async def aclose(self, timeout: float | None = 5.0) -> None: ...


__all__ = [
    "ModelController",
]

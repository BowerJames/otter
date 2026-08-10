from __future__ import annotations

from typing import Protocol

from otter_ai_core.data_models.context import (
    AssistantContextItem,
    ToolResultContextItem,
    UserContextItem,
)
from otter_ai_core.data_models.events import (
    BranchMoved,
    CompactionDone,
    InputEvent,
)

from ..capabilities.subscribable import Subscribable
from ..capabilities.task_runner import TaskRunner


class ModelController(Subscribable, TaskRunner, Protocol):
    def is_idle(self) -> bool: ...

    async def wait_for_idle(self) -> None: ...

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


__all__ = [
    "ModelController",
]

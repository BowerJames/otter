from __future__ import annotations

from typing import Protocol

from otter_ai_core.context import (
    AssistantContextItem,
    ToolResultContextItem,
    UserContextItem,
)
from otter_ai_core.data_models import (
    BranchMoved,
    CompactionDone,
    InputEvent,
    ServerContextEventType,
)

from .subscribable import Subscribable
from .task_runner import TaskRunner


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


# String event names the controller's Bus is keyed on. They alias the canonical
# ServerContextEventType members (the single source of truth) so subscribers can
# refer to a stable name without importing the model-connection enum.
RESPONSE_STARTED: str = ServerContextEventType.RESPONSE_STARTED
RESPONSE_UPDATED: str = ServerContextEventType.RESPONSE_UPDATED
RESPONSE_DONE: str = ServerContextEventType.RESPONSE_DONE
USER_ITEM_ADDED: str = ServerContextEventType.USER_ITEM_ADDED
USER_ITEM_UPDATED: str = ServerContextEventType.USER_ITEM_UPDATED
TOOL_RESULT_ADDED: str = ServerContextEventType.TOOL_RESULT_ADDED
COMPACTION_DONE: str = ServerContextEventType.COMPACTION_DONE
BRANCH_MOVED: str = ServerContextEventType.BRANCH_MOVED


__all__ = [
    "ModelController",
    "RESPONSE_STARTED",
    "RESPONSE_UPDATED",
    "RESPONSE_DONE",
    "USER_ITEM_ADDED",
    "USER_ITEM_UPDATED",
    "TOOL_RESULT_ADDED",
    "COMPACTION_DONE",
    "BRANCH_MOVED",
]

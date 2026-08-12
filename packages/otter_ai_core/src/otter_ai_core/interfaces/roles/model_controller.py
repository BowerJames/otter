from __future__ import annotations

from typing import Protocol

from otter_ai_core.data_models.context import (
    AssistantContextItem,
    ToolResultContextItem,
    UserContextItem,
)

from ..capabilities.binary_state_machine import BinaryStateMachine
from ..capabilities.subscribable import Subscribable
from ..capabilities.task_runner import TaskRunner


class ModelController(Subscribable, TaskRunner, BinaryStateMachine, Protocol):
    async def add_message(self, text: str) -> UserContextItem: ...

    async def add_tool_result(
        self, tool_call_id: str, tool_name: str, result: object
    ) -> ToolResultContextItem: ...

    async def generate(self) -> AssistantContextItem: ...


__all__ = [
    "ModelController",
]

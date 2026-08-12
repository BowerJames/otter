from __future__ import annotations

from typing import Protocol

from otter_ai_core.data_models.events import (
    ServerContextEvent,
)

from ..capabilities.binary_state_machine import BinaryStateMachine
from ..capabilities.stream import Stream


class ModelConnection(Stream[ServerContextEvent], BinaryStateMachine, Protocol):
    def add_user_message(self, text: str) -> None: ...

    def add_tool_result(self, tool_call_id: str, tool_name: str, result: object) -> None: ...

    def generate(self) -> None: ...

    def abort(self) -> None: ...

    def end(self) -> None: ...


__all__ = [
    "ModelConnection",
]

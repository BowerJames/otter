from collections.abc import Awaitable
from types import TracebackType
from typing import Protocol, Self

from otter_ai_core.conversation import AssistantMessage, ToolResultMessage, UserMessage


class Model(Protocol):
    def __aenter__(self) -> Awaitable[Self]: ...

    def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Awaitable[bool | None]: ...

    def add_user_message(self, text: str) -> Awaitable[UserMessage]: ...

    def add_tool_result_message(
        self, tool_call_id: str, text: str
    ) -> Awaitable[ToolResultMessage]: ...

    def generate(self) -> Awaitable[AssistantMessage]: ...

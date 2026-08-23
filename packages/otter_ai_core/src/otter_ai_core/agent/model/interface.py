from collections.abc import Awaitable
from typing import Protocol

from otter_ai_core.conversation import AssistantMessage, ToolResultMessage, UserMessage


class Model(Protocol):
    def add_user_message(self, text: str) -> Awaitable[UserMessage]: ...

    def add_tool_result_message(
        self, tool_call_id: str, text: str
    ) -> Awaitable[ToolResultMessage]: ...

    def generate(self) -> Awaitable[AssistantMessage]: ...

from collections.abc import Awaitable
from typing import Protocol

from otter_ai_core.conversation import AssistantMessage, ToolResultMessage, UserMessage


class Model(Protocol):
    """Abstraction over a chat model that owns the conversation history.

    A Model accumulates user, tool-result, and assistant messages and
    produces assistant responses via `generate`. Adapters are responsible
    for persisting history; the abstraction promises messages are recorded
    in the order the caller adds or generates them.
    """

    def add_user_message(self, text: str) -> Awaitable[UserMessage]:
        """Sends a user message to the model. Message is recorded if successfully awaited."""
        ...

    def add_tool_result_message(self, tool_call_id: str, text: str) -> Awaitable[ToolResultMessage]:
        """Sends a tool result message to the model. Message is recorded if
        successfully awaited."""
        ...

    def generate(self) -> Awaitable[AssistantMessage]:
        """Generates the next assistant message. Message is recorded if successfully awaited."""
        ...

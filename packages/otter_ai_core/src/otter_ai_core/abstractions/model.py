from collections.abc import Awaitable
from types import TracebackType
from typing import Protocol, Self

from otter_ai_core.types import AssistantMessage, ToolResultMessage, UserMessage


class Model(Protocol):
    """Abstraction over a chat model with an explicit session lifecycle.

    A model that has been exited cannot be entered again. Models receive
    their initial message context at construction via their factory and
    hold conversation history for their own generation needs; the durable
    record of a conversation lives in the session manager. Messages are
    recorded in the order the caller adds or generates them."""

    def add_user_message(self, text: str) -> Awaitable[UserMessage]:
        """Sends a user message to the model. Message is recorded if successfully
        awaited. Raises RuntimeError if called outside an active session."""
        ...

    def add_tool_result_message(self, tool_call_id: str, text: str) -> Awaitable[ToolResultMessage]:
        """Sends a tool result message to the model. `tool_call_id` must be the
        id of a tool call in the model's current context. Message is recorded
        if successfully awaited. Raises RuntimeError if called outside an
        active session."""
        ...

    def generate(self) -> Awaitable[AssistantMessage]:
        """Generates the next assistant message. Message is recorded if
        successfully awaited. Raises RuntimeError if called outside an active
        session."""
        ...

    def __aenter__(self) -> Awaitable[Self]:
        """Acquires any resources required for interacting with the model."""
        ...

    def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Awaitable[bool | None]:
        """Releases the resources acquired by `__aenter__` and ends the session.
        Exceptions raised in the session body are not suppressed."""
        ...

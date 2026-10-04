"""What an agent needs from a conversation with a model, whichever provider serves it."""

from collections.abc import Sequence
from typing import Protocol

from otter.messages import AssistantMessage, ToolSpec, UserPart


class Conversation(Protocol):
    """One conversation with one model: it holds the history and generates the next turn."""

    def add_user_message(self, content: Sequence[UserPart]) -> None:
        """Append a user turn; it is sent to the model on the next `generate`."""
        ...

    def add_tool_result(self, tool_call_id: str, text: str) -> None:
        """Append the result of a tool call the model asked for in its last turn."""
        ...

    async def generate(self) -> AssistantMessage:
        """Send the conversation so far to the model and return the turn it produces.

        The returned turn joins the history. If generating fails, the error propagates
        and the history is left as it was.
        """
        ...


class ConversationFactory(Protocol):
    """Starts a new, empty conversation with `model`."""

    def __call__(
        self, model: str, *, system: str | None = None, tools: Sequence[ToolSpec] = ()
    ) -> Conversation: ...

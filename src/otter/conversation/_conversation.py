"""What an agent needs from a conversation with a model, whichever provider serves it."""

from collections.abc import Sequence
from types import TracebackType
from typing import Protocol, Self

from otter.core.domain.messages import AssistantMessage, ContextEntry, ToolSpec, UserPart


class Conversation(Protocol):
    """One conversation with one model: it holds the history and generates the next turn.

    A conversation is an async context manager, and may hold something open for as long
    as it is entered, such as a connection to the model: use it in `async with`, and
    generate its turns inside.
    """

    def add_user_message(self, content: Sequence[UserPart]) -> None:
        """Append a user turn; it is sent to the model on the next `generate`."""
        ...

    def add_tool_result(self, tool_call_id: str, text: str) -> None:
        """Append the result of a tool call the model asked for in its last turn."""
        ...

    async def generate(self) -> AssistantMessage:
        """Send the conversation so far to the model and return the turn it produces.

        The returned turn joins the history. If generating fails, the error propagates
        and the history is left as it was. A conversation that holds something open
        raises `RuntimeError` if it has not been entered.
        """
        ...

    async def __aenter__(self) -> Self:
        """Enter the conversation, which is returned, taking hold of anything it needs open.

        If that fails, the error propagates and the conversation has not been entered.
        """
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave the conversation, letting go of anything held open."""
        ...


class ConversationFactory(Protocol):
    """Starts a new conversation with `model`.

    `context` is the history the conversation starts out with, oldest first; leave it
    out to start empty. It is sent to the model as it stands, ahead of anything added
    later. The thinking in its assistant turns is not sent.
    """

    def __call__(
        self,
        model: str,
        *,
        system: str | None = None,
        tools: Sequence[ToolSpec] = (),
        context: Sequence[ContextEntry] = (),
    ) -> Conversation: ...

"""What a chat is to its callers."""

from typing import Protocol


class Chat(Protocol):
    """A chat between a user and an agent session."""

    async def __call__(self) -> None:
        """Hold the chat; return once the user quits.

        The session is started and the screen put up as the chat begins, and both are
        let go of as it ends. If either cannot be started, the error propagates.
        """
        ...

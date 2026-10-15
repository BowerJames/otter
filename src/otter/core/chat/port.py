"""What a chat needs: a session to hold, and a screen to hold it on."""

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from otter.core.domain.messages import ContextEntry

from .data import SessionUpdate, Status, TranscriptLine


class ChatPort(Protocol):
    """An agent session, and the screen a chat with it is shown on."""

    async def open(self) -> None:
        """Start the session and put the screen up.

        If either fails, the error propagates and neither is left open.
        """
        ...

    async def close(self) -> None:
        """Take the screen down and end the session."""
        ...

    def history(self) -> Sequence[ContextEntry]:
        """Return the session's conversation so far, oldest first."""
        ...

    def prompt(self, text: str) -> None:
        """Put `text` to the session; raises if the session will not take it."""
        ...

    def updates(self) -> AsyncIterator[SessionUpdate]:
        """Run the session, yielding what happens in it as it happens.

        Raises what the session raises if it fails; reading again picks up from there.
        Finishes once the session has ended.
        """
        ...

    def show(self, line: TranscriptLine) -> None:
        """Add `line` to the end of the transcript on the screen."""
        ...

    def set_status(self, status: Status) -> None:
        """Show what the chat is doing, in place of the status shown before."""
        ...

    def submissions(self) -> AsyncIterator[str]:
        """Each message the user submits, as it is submitted. Finishes once the user quits."""
        ...

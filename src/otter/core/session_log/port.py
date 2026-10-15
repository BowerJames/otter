"""What a session log needs from the place its text is kept."""

from typing import Protocol


class SessionLogPort(Protocol):
    """The text of one log, which is only ever added to."""

    def read(self) -> str:
        """Return all the text added so far: empty if none has been."""
        ...

    def append(self, text: str) -> None:
        """Add `text` to the end.

        If it cannot be added, the error propagates and the text is as it was.
        """
        ...

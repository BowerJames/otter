"""Where the context of an agent session is kept, so a later session can pick it up."""

from collections.abc import Sequence
from typing import Protocol

from otter.messages import ContextEntry


class SessionManager(Protocol):
    """An append-only store of the context entries of one agent session.

    Entries are only ever added, never changed or removed, and are kept in the order
    they were appended.
    """

    def append(self, entry: ContextEntry) -> None:
        """Add `entry` after every entry already stored.

        If the entry cannot be stored, the error propagates and the store is as it was.
        """
        ...

    def entries(self) -> Sequence[ContextEntry]:
        """Return every entry stored so far, oldest first.

        What is returned does not change when more entries are appended.
        """
        ...

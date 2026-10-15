"""What a session log is to its callers."""

from collections.abc import Sequence
from typing import Protocol

from otter.core.domain.messages import ContextEntry


class SessionLog(Protocol):
    """An append-only record of the context entries of one agent session.

    Entries are only ever added, never changed or removed, and are read back in the
    order they were appended, so a later session can pick up where this one left off.
    """

    def append(self, entry: ContextEntry) -> None:
        """Add `entry` after every entry already in the log.

        If the entry cannot be written, the error propagates and the log is as it was.
        """
        ...

    def entries(self) -> Sequence[ContextEntry]:
        """Return every entry in the log, oldest first.

        What is returned does not change when more entries are appended. Raises
        `json.JSONDecodeError` for a line of the log that is not JSON, and `NotAnEntry`
        for one that is JSON but not an entry.
        """
        ...

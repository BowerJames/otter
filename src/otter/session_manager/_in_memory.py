"""A session manager that keeps a session's context in memory."""

from collections.abc import Iterable, Sequence

from otter.core.domain.messages import ContextEntry

from ._session_manager import SessionManager


def create_in_memory_session_manager(entries: Iterable[ContextEntry] = ()) -> SessionManager:
    """Return a session manager that keeps its entries in memory.

    The entries last as long as the session manager does. `entries` are what it starts
    out holding, oldest first; leave it out to start empty.
    """
    return InMemorySessionManager(entries)


class InMemorySessionManager:
    """An append-only store of the context entries of one agent session, held in memory.

    The entries last as long as the instance does. `entries` are what the store starts
    out holding, oldest first; leave it out to start empty.
    """

    def __init__(self, entries: Iterable[ContextEntry] = ()) -> None:
        self._entries: list[ContextEntry] = list(entries)

    def append(self, entry: ContextEntry) -> None:
        """Add `entry` after every entry already stored."""
        self._entries.append(entry)

    def entries(self) -> Sequence[ContextEntry]:
        """Return every entry stored so far, oldest first.

        What is returned does not change when more entries are appended.
        """
        return tuple(self._entries)

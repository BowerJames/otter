"""A session log kept as JSON Lines: one entry to a line, in the order appended."""

from collections.abc import Sequence

from otter.core.domain.messages import ContextEntry

from .json_lines import entries_of, line_of
from .port import SessionLogPort


class SessionLogImpl:
    """A session log whose entries are kept as lines of JSON in the text of `port`.

    Text the port already holds is entries appended before, so a log made over it picks
    up where they left off. Nothing is read or written until the log is used.
    """

    def __init__(self, port: SessionLogPort) -> None:
        self._port = port

    def append(self, entry: ContextEntry) -> None:
        self._port.append(line_of(entry))

    def entries(self) -> Sequence[ContextEntry]:
        return entries_of(self._port.read())

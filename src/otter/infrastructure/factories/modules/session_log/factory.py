import os

from otter.core.session_log import SessionLog, SessionLogImpl
from otter.infrastructure.factories.adapters.session_log.in_memory import (
    create_in_memory_adapter,
)
from otter.infrastructure.factories.adapters.session_log.local_file import (
    create_local_file_adapter,
)


def create_file_session_log(path: str | os.PathLike[str]) -> SessionLog:
    """Return a session log kept in the JSON Lines file at `path`.

    A file that already holds a log is picked up where it left off. One that does not
    exist is made, along with any directories it sits in, when the first entry is
    appended.
    """
    return SessionLogImpl(create_local_file_adapter(path))


def create_in_memory_session_log() -> SessionLog:
    """Return a session log kept in memory: it starts out empty, and lasts as long as it does."""
    return SessionLogImpl(create_in_memory_adapter())

import os
from pathlib import Path

from otter.core.session_log import SessionLogPort
from otter.infrastructure.adapters.session_log.local_file import LocalFileAdapter


def create_local_file_adapter(path: str | os.PathLike[str]) -> SessionLogPort:
    """Return a session log's text, kept in the UTF-8 file at `path`."""
    return LocalFileAdapter(Path(path))

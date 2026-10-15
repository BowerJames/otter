"""A session log's text, kept in a UTF-8 file on this machine."""

from pathlib import Path

from otter.core.session_log import SessionLogPort


class LocalFileAdapter(SessionLogPort):
    """Keeps the text in the UTF-8 file at `path`.

    A file that does not exist holds no text: it is made, along with any directories it
    sits in, when text is first appended. Nothing is read or written until then.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> str:
        try:
            return self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def append(self, text: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            file.write(text)

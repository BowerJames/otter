"""A session log's text, kept in memory."""

from otter.core.session_log import SessionLogPort


class InMemoryAdapter(SessionLogPort):
    """Keeps the text in memory, for as long as the adapter lasts. It starts out empty."""

    def __init__(self) -> None:
        self._text = ""

    def read(self) -> str:
        return self._text

    def append(self, text: str) -> None:
        self._text += text

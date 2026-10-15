"""Test adapters for the session log's port."""

from otter.core.session_log import SessionLogPort


class FakeSessionLogAdapter(SessionLogPort):
    """Holds the log's text in `text`."""

    def __init__(self, text: str = "") -> None:
        self.text = text

    def read(self) -> str:
        return self.text

    def append(self, text: str) -> None:
        self.text += text

"""Test adapters for what the TUI command opens chats through."""

from otter.core.chat import Chat
from otter.infrastructure.entrypoints.tui import ChatSettings


class FakeChat(Chat):
    """A chat that records that it was held, and raises `failing` if it is set."""

    def __init__(self) -> None:
        self.held = False
        self.failing: Exception | None = None

    async def __call__(self) -> None:
        if self.failing is not None:
            raise self.failing
        self.held = True


class FakeOpenChat:
    """Opens `chat` for any settings, recording them in `opened`.

    While `refusing` is set, opening raises it.
    """

    def __init__(self) -> None:
        self.chat = FakeChat()
        self.opened: list[ChatSettings] = []
        self.refusing: Exception | None = None

    def __call__(self, settings: ChatSettings) -> Chat:
        if self.refusing is not None:
            raise self.refusing
        self.opened.append(settings)
        return self.chat

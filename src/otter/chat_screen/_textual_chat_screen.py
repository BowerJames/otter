"""The Textual app a chat is shown in, and the chat screen that it is."""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from types import TracebackType
from typing import Self, assert_never

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, RichLog

from ._chat_screen import (
    AssistantLine,
    ErrorLine,
    NoticeLine,
    Status,
    ThinkingLine,
    ToolCallLine,
    ToolResultLine,
    TranscriptLine,
    UserLine,
)


def _drawn(line: TranscriptLine) -> Text:
    match line:
        case UserLine(text):
            return Text(f"you: {text}", style="bold cyan")
        case ThinkingLine(text):
            return Text(text, style="dim italic")
        case AssistantLine(text):
            return Text(text)
        case ToolCallLine(name, arguments):
            return Text(f"tool: {name}({json.dumps(dict(arguments))})", style="yellow")
        case ToolResultLine(text):
            return Text(f"result: {text}", style="dim yellow")
        case ErrorLine(text):
            return Text(f"error: {text}", style="bold red")
        case NoticeLine(text):
            return Text(text, style="dim")
        case _:
            assert_never(line)


class _ChatApp(App[None]):
    CSS = """
    RichLog { padding: 0 1; }
    Input { dock: bottom; }
    """

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title
        self.mounted = asyncio.Event()
        # None once the app has gone down: nothing more will be submitted.
        self.submitted: asyncio.Queue[str | None] = asyncio.Queue()

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(wrap=True)
        yield Input(placeholder="Message the agent, then press Enter")
        yield Footer()

    def on_mount(self) -> None:
        self.title = self._title
        self.query_one(Input).focus()
        self.mounted.set()

    def on_input_submitted(self, message: Input.Submitted) -> None:
        self.submitted.put_nowait(message.value)
        message.input.clear()


class TextualChatScreen:
    def __init__(self, title: str, terminal: Callable[[App[None]], Awaitable[None]]) -> None:
        self._app = _ChatApp(title)
        self._terminal = terminal
        self._running: asyncio.Future[None] | None = None

    def show(self, line: TranscriptLine) -> None:
        if self._app.is_running:
            self._app.query_one(RichLog).write(_drawn(line))

    def set_status(self, status: Status) -> None:
        if self._app.is_running:
            self._app.sub_title = status

    async def submissions(self) -> AsyncIterator[str]:
        while (text := await self._app.submitted.get()) is not None:
            yield text
        # Left for whoever asks next: the user has quit for them too.
        self._app.submitted.put_nowait(None)

    async def __aenter__(self) -> Self:
        self._running = asyncio.ensure_future(self._terminal(self._app))
        self._running.add_done_callback(lambda _: self._app.submitted.put_nowait(None))
        mounted = asyncio.ensure_future(self._app.mounted.wait())
        try:
            await asyncio.wait([self._running, mounted], return_when=asyncio.FIRST_COMPLETED)
        finally:
            mounted.cancel()
        if self._running.done():
            # The app went down before it was up: whatever brought it down propagates.
            self._running.result()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._running is not None:
            self._app.exit()
            await self._running

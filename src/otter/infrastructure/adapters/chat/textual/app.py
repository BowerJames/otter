"""The Textual app a chat is drawn in."""

import asyncio
import json
from typing import assert_never

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, RichLog

from otter.core.chat import (
    AssistantLine,
    ErrorLine,
    NoticeLine,
    ThinkingLine,
    ToolCallLine,
    ToolResultLine,
    TranscriptLine,
    UserLine,
)


class ChatApp(App[None]):
    """A transcript filling the screen above a box the user types into.

    Entering what is typed submits it and empties the box. The status is shown beside
    the title. The user quits with ctrl+q.
    """

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

    def draw(self, line: TranscriptLine) -> None:
        self.query_one(RichLog).write(_drawn(line))


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

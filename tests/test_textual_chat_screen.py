"""Behaviour of the Textual chat screen, observed on a terminal that is not there: what it
shows there, and what is typed into it.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from textual.app import App
from textual.pilot import Pilot
from textual.widgets import Input, RichLog

from otter.chat_screen import (
    AssistantLine,
    ChatScreen,
    ErrorLine,
    NoticeLine,
    ThinkingLine,
    ToolCallLine,
    ToolResultLine,
    TranscriptLine,
    UserLine,
    create_textual_chat_screen,
)


class HeadlessTerminal:
    """A test adapter for the terminal: runs the app with no terminal under it, and lets
    the test read what the app is showing and press its keys.
    """

    def __init__(self) -> None:
        self.running = False
        self._down = asyncio.Event()
        self._app: App[None] | None = None
        self._pilot: Pilot[object] | None = None

    async def __call__(self, app: App[None]) -> None:
        self._app = app
        self.running = True
        try:
            await app.run_async(headless=True, size=(80, 24), auto_pilot=self._take)
        finally:
            self.running = False
            self._down.set()

    async def _take(self, pilot: Pilot[object]) -> None:
        self._pilot = pilot

    @property
    def app(self) -> App[None]:
        assert self._app is not None, "nothing has been run on the terminal"
        return self._app

    @property
    def pilot(self) -> Pilot[object]:
        assert self._pilot is not None, "nothing is running on the terminal"
        return self._pilot

    @property
    def title(self) -> str:
        return self.app.title

    @property
    def status(self) -> str:
        return self.app.sub_title

    @property
    def typed(self) -> str:
        """What is in the box the user types into."""
        return self.app.query_one(Input).value

    async def transcript(self) -> list[str]:
        await self.pilot.pause()
        return [line.text.rstrip() for line in self.app.query_one(RichLog).lines]

    async def press(self, *keys: str) -> None:
        await self.pilot.press(*keys)
        await self.pilot.pause()

    async def quit(self) -> None:
        """Press the key that quits, and wait for the app to go down."""
        await self.pilot.press("ctrl+q")
        await self._down.wait()

    async def submit(self, text: str) -> None:
        await self.press(*("space" if key == " " else key for key in text), "enter")


@pytest.fixture
def terminal() -> HeadlessTerminal:
    return HeadlessTerminal()


@pytest.fixture
async def screen(terminal: HeadlessTerminal) -> AsyncIterator[ChatScreen]:
    """The screen, up for as long as the test lasts."""
    async with create_textual_chat_screen("glm-5.3 (zai)", terminal=terminal) as screen:
        yield screen


async def test_a_screen_that_is_up_is_on_the_terminal_under_its_title(
    terminal: HeadlessTerminal, screen: ChatScreen
) -> None:
    assert terminal.running
    assert terminal.title == "glm-5.3 (zai)"


async def test_a_screen_that_has_been_left_is_off_the_terminal(terminal: HeadlessTerminal) -> None:
    async with create_textual_chat_screen("glm-5.3 (zai)", terminal=terminal):
        pass

    assert not terminal.running


@pytest.mark.parametrize(
    "line, shown",
    [
        (UserLine("What is in a.txt?"), "you: What is in a.txt?"),
        (ThinkingLine("The file is the place to look."), "The file is the place to look."),
        (AssistantLine("Let me look."), "Let me look."),
        (
            ToolCallLine("read_file", {"path": "a.txt", "lines": [1, 20]}),
            'tool: read_file({"path": "a.txt", "lines": [1, 20]})',
        ),
        (ToolResultLine("file contents"), "result: file contents"),
        (ErrorLine("connection lost"), "error: connection lost"),
        (NoticeLine("Send another message to try again."), "Send another message to try again."),
    ],
)
async def test_a_line_that_is_shown_joins_the_transcript_marked_for_what_it_is(
    line: TranscriptLine, shown: str, terminal: HeadlessTerminal, screen: ChatScreen
) -> None:
    screen.show(line)

    assert await terminal.transcript() == [shown]


async def test_the_status_that_is_set_is_shown(
    terminal: HeadlessTerminal, screen: ChatScreen
) -> None:
    screen.set_status("working")

    assert terminal.status == "working"


async def test_a_message_the_user_types_and_enters_is_a_submission(
    terminal: HeadlessTerminal, screen: ChatScreen
) -> None:
    submissions = screen.submissions()

    await terminal.submit("Hi")

    assert await asyncio.wait_for(anext(submissions), timeout=1) == "Hi"


async def test_a_message_that_is_entered_leaves_the_box_empty_for_the_next(
    terminal: HeadlessTerminal, screen: ChatScreen
) -> None:
    await terminal.submit("Hi")

    assert terminal.typed == ""


async def test_submissions_finish_once_the_user_quits(
    terminal: HeadlessTerminal, screen: ChatScreen
) -> None:
    submissions = screen.submissions()

    await terminal.quit()

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(submissions), timeout=1)


async def test_a_line_shown_after_the_user_quit_is_dropped(
    terminal: HeadlessTerminal, screen: ChatScreen
) -> None:
    await terminal.quit()

    screen.show(AssistantLine("Too late."))
    screen.set_status("idle")


async def test_a_terminal_the_screen_cannot_go_up_on_propagates() -> None:
    async def no_terminal(app: App[None]) -> None:
        raise OSError("not a terminal")

    with pytest.raises(OSError, match="not a terminal"):
        async with create_textual_chat_screen("glm-5.3 (zai)", terminal=no_terminal):
            pass

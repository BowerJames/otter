"""Behaviour of the Textual adapter, driven through the chat's port and observed at a fake
session and on a terminal that is not there.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from textual.app import App

from otter.core.agent_session import Idle as SessionIdle
from otter.core.chat import (
    AssistantLine,
    ChatPort,
    ErrorLine,
    Idle,
    NoticeLine,
    ThinkingLine,
    ToolCallLine,
    ToolResultLine,
    TranscriptLine,
    UserLine,
)
from otter.core.domain.messages import AssistantMessage, TextPart, UserMessage
from otter.infrastructure.adapters.chat.textual import TextualAdapter

from .adapters import FakeAgentSession, HeadlessTerminal

HELLO = UserMessage((TextPart("Hello"),))


@pytest.fixture
def session() -> FakeAgentSession:
    return FakeAgentSession()


@pytest.fixture
def terminal() -> HeadlessTerminal:
    return HeadlessTerminal()


@pytest.fixture
async def adapter(session: FakeAgentSession, terminal: HeadlessTerminal) -> AsyncIterator[ChatPort]:
    """The adapter, opened for as long as the test lasts."""
    adapter = TextualAdapter(session, "glm-5.3 (zai)", terminal)
    await adapter.open()
    yield adapter
    await adapter.close()


# Opening and closing


async def test_opening_enters_the_session_and_puts_the_screen_up_under_its_title(
    session: FakeAgentSession, terminal: HeadlessTerminal, adapter: ChatPort
) -> None:
    assert session.calls == ["enter"]
    assert terminal.running
    assert terminal.title == "glm-5.3 (zai)"


async def test_closing_takes_the_screen_down_and_leaves_the_session(
    session: FakeAgentSession, terminal: HeadlessTerminal
) -> None:
    adapter = TextualAdapter(session, "glm-5.3 (zai)", terminal)
    await adapter.open()

    await adapter.close()

    assert not terminal.running
    assert session.calls == ["enter", "leave"]


async def test_a_session_that_cannot_be_entered_propagates_and_no_screen_goes_up(
    session: FakeAgentSession, terminal: HeadlessTerminal
) -> None:
    session.fail_to_enter = ConnectionError("no route")

    with pytest.raises(ConnectionError, match=r"^no route$"):
        await TextualAdapter(session, "glm-5.3 (zai)", terminal).open()

    assert not terminal.running


async def test_a_screen_that_cannot_go_up_propagates_and_the_session_is_left(
    session: FakeAgentSession,
) -> None:
    async def no_terminal(app: App[None]) -> None:
        raise OSError("not a terminal")

    with pytest.raises(OSError, match=r"^not a terminal$"):
        await TextualAdapter(session, "glm-5.3 (zai)", no_terminal).open()

    assert session.calls == ["enter", "leave"]


# The session


async def test_the_history_is_the_sessions(session: FakeAgentSession, adapter: ChatPort) -> None:
    session.started_with = [HELLO]

    assert list(adapter.history()) == [HELLO]


async def test_a_prompt_is_put_to_the_session(session: FakeAgentSession, adapter: ChatPort) -> None:
    adapter.prompt("Hello")

    assert session.prompts == ["Hello"]


async def test_the_updates_are_what_the_session_streams_the_rest_it_comes_to_included(
    session: FakeAgentSession, adapter: ChatPort
) -> None:
    session.events = [HELLO, AssistantMessage((TextPart("Hi!"),)), SessionIdle()]

    assert [update async for update in adapter.updates()] == [
        HELLO,
        AssistantMessage((TextPart("Hi!"),)),
        Idle(),
    ]


# The screen


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
    line: TranscriptLine, shown: str, terminal: HeadlessTerminal, adapter: ChatPort
) -> None:
    adapter.show(line)

    assert await terminal.transcript() == [shown]


async def test_the_status_that_is_set_is_shown(
    terminal: HeadlessTerminal, adapter: ChatPort
) -> None:
    adapter.set_status("working")

    assert terminal.status == "working"


async def test_a_message_the_user_types_and_enters_is_a_submission(
    terminal: HeadlessTerminal, adapter: ChatPort
) -> None:
    submissions = adapter.submissions()

    await terminal.submit("Hi")

    assert await asyncio.wait_for(anext(submissions), timeout=1) == "Hi"


async def test_a_message_that_is_entered_leaves_the_box_empty_for_the_next(
    terminal: HeadlessTerminal, adapter: ChatPort
) -> None:
    await terminal.submit("Hi")

    assert terminal.typed == ""


async def test_submissions_finish_once_the_user_quits(
    terminal: HeadlessTerminal, adapter: ChatPort
) -> None:
    submissions = adapter.submissions()

    await terminal.quit()

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(submissions), timeout=1)


async def test_a_line_shown_after_the_user_quit_is_dropped(
    terminal: HeadlessTerminal, adapter: ChatPort
) -> None:
    await terminal.quit()

    adapter.show(AssistantLine("Too late."))
    adapter.set_status("idle")

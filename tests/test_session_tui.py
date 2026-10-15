"""Behaviour of a session TUI, observed at a fake agent session and a fake chat screen."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Self

import pytest

from otter.agent_session import AssistantTurn, Idle, SessionEvent, ToolResult, UserTurn
from otter.chat_screen import (
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
from otter.core.domain.messages import (
    AssistantMessage,
    AudioPart,
    ContextEntry,
    ImagePart,
    ImageUrlPart,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from otter.tui import create_session_tui


class FakeSession:
    """A test adapter for the agent session: records the prompts made to it, and its
    stream yields whatever the test says `happens`, as it says so.

    A stream `fails` by raising the error given. Ending the session finishes its stream
    and makes further prompts raise.
    """

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.streams_started = 0
        self.streams_finished = 0
        self._ended = False
        self._happening: asyncio.Queue[SessionEvent | Exception | None] = asyncio.Queue()

    def happens(self, *events: SessionEvent) -> None:
        for event in events:
            self._happening.put_nowait(event)

    def fails(self, error: Exception) -> None:
        self._happening.put_nowait(error)

    def prompt(
        self,
        text: str,
        *,
        images: Sequence[ImagePart | ImageUrlPart] = (),
        audio: Sequence[AudioPart] = (),
    ) -> None:
        if self._ended:
            raise RuntimeError("the session has ended")
        self.prompts.append(text)

    async def stream(self) -> AsyncGenerator[SessionEvent, None]:
        self.streams_started += 1
        try:
            while True:
                happening = await self._happening.get()
                if happening is None:
                    return
                if isinstance(happening, Exception):
                    raise happening
                yield happening
        finally:
            self.streams_finished += 1

    async def wait_for_idle(self) -> None:
        raise NotImplementedError

    def end(self) -> None:
        self._ended = True
        self._happening.put_nowait(None)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.end()


class FakeScreen:
    """A test adapter for the chat screen: records the lines and statuses it is shown, and
    hands over the messages the test has the user `submit`, until the user `quit`s.
    """

    def __init__(self) -> None:
        self.transcript: list[TranscriptLine] = []
        self.statuses: list[Status] = []
        self._submitted: asyncio.Queue[str | None] = asyncio.Queue()

    def submit(self, text: str) -> None:
        self._submitted.put_nowait(text)

    def quit(self) -> None:
        self._submitted.put_nowait(None)

    def show(self, line: TranscriptLine) -> None:
        self.transcript.append(line)

    def set_status(self, status: Status) -> None:
        self.statuses.append(status)

    async def submissions(self) -> AsyncGenerator[str, None]:
        while (text := await self._submitted.get()) is not None:
            yield text

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        pass


async def settled() -> None:
    """Let everything that can run without the test's say-so run."""
    for _ in range(10):
        await asyncio.sleep(0)


@asynccontextmanager
async def chatting(
    session: FakeSession, screen: FakeScreen, context: Sequence[ContextEntry] = ()
) -> AsyncIterator[None]:
    """Hold the chat for as long as the block lasts: the user quits at the end of it.

    Wraps the factory, and settles before and after the block, so a test only says what
    the user and the session do.
    """
    chat = asyncio.ensure_future(create_session_tui(session, screen, context=context)())
    await settled()
    try:
        yield
        await settled()
    finally:
        screen.quit()
        await asyncio.wait_for(chat, timeout=1)


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def screen() -> FakeScreen:
    return FakeScreen()


async def test_the_chat_lasts_until_the_user_quits(
    session: FakeSession, screen: FakeScreen
) -> None:
    chat = asyncio.ensure_future(create_session_tui(session, screen)())
    await settled()
    still_going = not chat.done()

    screen.quit()
    await asyncio.wait_for(chat, timeout=1)

    assert still_going


async def test_a_message_the_user_submits_is_put_to_the_session(
    session: FakeSession, screen: FakeScreen
) -> None:
    async with chatting(session, screen):
        screen.submit("What is in a.txt?")

    assert session.prompts == ["What is in a.txt?"]


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
async def test_a_blank_message_is_not_put_to_the_session(
    blank: str, session: FakeSession, screen: FakeScreen
) -> None:
    async with chatting(session, screen):
        screen.submit(blank)

    assert session.prompts == []


async def test_a_turn_of_the_users_that_joins_the_conversation_is_shown(
    session: FakeSession, screen: FakeScreen
) -> None:
    async with chatting(session, screen):
        session.happens(UserTurn((TextPart("What is in a.txt?"),)))

    assert screen.transcript == [UserLine("What is in a.txt?")]


async def test_what_is_not_text_in_a_turn_of_the_users_is_shown_as_an_attachment(
    session: FakeSession, screen: FakeScreen
) -> None:
    async with chatting(session, screen):
        session.happens(
            UserTurn(
                (
                    TextPart("Look and listen"),
                    ImagePart(data="iVBORw==", media_type="image/png"),
                    AudioPart(data="UklGRg==", format="wav"),
                )
            )
        )

    assert screen.transcript == [UserLine("Look and listen [attachment] [attachment]")]


async def test_a_turn_of_the_models_is_shown_part_by_part(
    session: FakeSession, screen: FakeScreen
) -> None:
    async with chatting(session, screen):
        session.happens(
            AssistantTurn(
                AssistantMessage(
                    (
                        ThinkingPart("The file is the place to look."),
                        TextPart("Let me look."),
                        ToolCall("call-1", "read_file", {"path": "a.txt"}),
                    )
                )
            )
        )

    assert screen.transcript == [
        ThinkingLine("The file is the place to look."),
        AssistantLine("Let me look."),
        ToolCallLine("read_file", {"path": "a.txt"}),
    ]


async def test_the_result_of_a_tool_the_model_asked_for_is_shown(
    session: FakeSession, screen: FakeScreen
) -> None:
    async with chatting(session, screen):
        session.happens(ToolResult("call-1", "file contents"))

    assert screen.transcript == [ToolResultLine("file contents")]


async def test_the_status_is_idle_once_the_session_comes_to_rest(
    session: FakeSession, screen: FakeScreen
) -> None:
    async with chatting(session, screen):
        session.happens(Idle())

    assert screen.statuses == ["idle"]


async def test_the_status_is_working_once_a_message_is_put_to_the_session(
    session: FakeSession, screen: FakeScreen
) -> None:
    async with chatting(session, screen):
        session.happens(Idle())
        await settled()
        screen.submit("What is in a.txt?")

    assert screen.statuses == ["idle", "working"]


async def test_a_message_the_session_will_not_take_is_shown_as_an_error(
    session: FakeSession, screen: FakeScreen
) -> None:
    session.end()

    async with chatting(session, screen):
        screen.submit("Anyone there?")

    assert screen.transcript == [ErrorLine("the session has ended")]
    assert screen.statuses == []


async def test_a_session_that_fails_is_shown_as_an_error_and_the_chat_goes_on(
    session: FakeSession, screen: FakeScreen
) -> None:
    async with chatting(session, screen):
        session.fails(ConnectionError("connection lost"))

    assert screen.transcript == [
        ErrorLine("connection lost"),
        NoticeLine("Send another message to try again."),
    ]
    assert screen.statuses == ["stopped"]


async def test_a_message_submitted_after_the_session_failed_has_it_streamed_again(
    session: FakeSession, screen: FakeScreen
) -> None:
    async with chatting(session, screen):
        session.fails(ConnectionError("connection lost"))
        await settled()
        screen.submit("Try again")
        await settled()
        session.happens(AssistantTurn(AssistantMessage((TextPart("Back with you."),))))

    assert screen.transcript[-1] == AssistantLine("Back with you.")


async def test_the_transcript_opens_with_the_context_the_chat_was_given(
    session: FakeSession, screen: FakeScreen
) -> None:
    context: list[ContextEntry] = [
        UserMessage((TextPart("What is in a.txt?"), ImageUrlPart("https://example.test/a.png"))),
        AssistantMessage(
            (
                ThinkingPart("The file is the place to look."),
                TextPart("Let me look."),
                ToolCall("call-1", "read_file", {"path": "a.txt"}),
            )
        ),
        ToolResultMessage("call-1", "file contents"),
    ]

    async with chatting(session, screen, context):
        pass

    assert screen.transcript == [
        UserLine("What is in a.txt? [attachment]"),
        ThinkingLine("The file is the place to look."),
        AssistantLine("Let me look."),
        ToolCallLine("read_file", {"path": "a.txt"}),
        ToolResultLine("file contents"),
    ]


async def test_the_session_is_no_longer_read_once_the_user_quits(
    session: FakeSession, screen: FakeScreen
) -> None:
    async with chatting(session, screen):
        pass

    assert (session.streams_started, session.streams_finished) == (1, 1)

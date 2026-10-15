"""Behaviour of a chat, observed at a fake session and screen."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from otter.core.chat import (
    AssistantLine,
    Chat,
    ChatImpl,
    ErrorLine,
    Idle,
    NoticeLine,
    ThinkingLine,
    ToolCallLine,
    ToolResultLine,
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

from .adapters import FakeChatAdapter


def setup(port: FakeChatAdapter) -> Chat:
    return ChatImpl(port)


async def settled() -> None:
    """Let everything that can run without the test's say-so run."""
    for _ in range(10):
        await asyncio.sleep(0)


@asynccontextmanager
async def chatting(port: FakeChatAdapter) -> AsyncIterator[None]:
    """Hold the chat for as long as the block lasts: the user quits at the end of it.

    Settles before and after the block, so a test only says what the user and the
    session do.
    """
    chat = asyncio.ensure_future(setup(port)())
    await settled()
    try:
        yield
        await settled()
    finally:
        port.quit()
        await asyncio.wait_for(chat, timeout=1)


@pytest.fixture
def port() -> FakeChatAdapter:
    return FakeChatAdapter()


async def test_the_chat_lasts_until_the_user_quits(port: FakeChatAdapter) -> None:
    chat = asyncio.ensure_future(setup(port)())
    await settled()
    still_going = not chat.done()

    port.quit()
    await asyncio.wait_for(chat, timeout=1)

    assert still_going


async def test_the_session_and_screen_are_opened_as_the_chat_begins_and_closed_as_it_ends(
    port: FakeChatAdapter,
) -> None:
    async with chatting(port):
        assert port.calls == ["open"]

    assert port.calls == ["open", "close"]


async def test_a_session_and_screen_that_cannot_be_opened_propagate_and_nothing_is_closed(
    port: FakeChatAdapter,
) -> None:
    port.fail_to_open = OSError("not a terminal")

    with pytest.raises(OSError, match=r"^not a terminal$"):
        await setup(port)()

    assert port.calls == []


async def test_a_message_the_user_submits_is_put_to_the_session(port: FakeChatAdapter) -> None:
    async with chatting(port):
        port.submit("What is in a.txt?")

    assert port.prompts == ["What is in a.txt?"]


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
async def test_a_blank_message_is_not_put_to_the_session(blank: str, port: FakeChatAdapter) -> None:
    async with chatting(port):
        port.submit(blank)

    assert port.prompts == []


async def test_a_turn_of_the_users_that_joins_the_conversation_is_shown(
    port: FakeChatAdapter,
) -> None:
    async with chatting(port):
        port.happens(UserMessage((TextPart("What is in a.txt?"),)))

    assert port.transcript == [UserLine("What is in a.txt?")]


async def test_what_is_not_text_in_a_turn_of_the_users_is_shown_as_an_attachment(
    port: FakeChatAdapter,
) -> None:
    async with chatting(port):
        port.happens(
            UserMessage(
                (
                    TextPart("Look and listen"),
                    ImagePart(data="iVBORw==", media_type="image/png"),
                    AudioPart(data="UklGRg==", format="wav"),
                )
            )
        )

    assert port.transcript == [UserLine("Look and listen [attachment] [attachment]")]


async def test_a_turn_of_the_models_is_shown_part_by_part(port: FakeChatAdapter) -> None:
    async with chatting(port):
        port.happens(
            AssistantMessage(
                (
                    ThinkingPart("The file is the place to look."),
                    TextPart("Let me look."),
                    ToolCall("call-1", "read_file", {"path": "a.txt"}),
                )
            )
        )

    assert port.transcript == [
        ThinkingLine("The file is the place to look."),
        AssistantLine("Let me look."),
        ToolCallLine("read_file", {"path": "a.txt"}),
    ]


async def test_the_result_of_a_tool_the_model_asked_for_is_shown(port: FakeChatAdapter) -> None:
    async with chatting(port):
        port.happens(ToolResultMessage("call-1", "file contents"))

    assert port.transcript == [ToolResultLine("file contents")]


async def test_the_status_is_idle_once_the_session_comes_to_rest(port: FakeChatAdapter) -> None:
    async with chatting(port):
        port.happens(Idle())

    assert port.statuses == ["idle"]


async def test_the_status_is_working_once_a_message_is_put_to_the_session(
    port: FakeChatAdapter,
) -> None:
    async with chatting(port):
        port.happens(Idle())
        await settled()
        port.submit("What is in a.txt?")

    assert port.statuses == ["idle", "working"]


async def test_a_message_the_session_will_not_take_is_shown_as_an_error(
    port: FakeChatAdapter,
) -> None:
    port.refusing = RuntimeError("the session has ended")

    async with chatting(port):
        port.submit("Anyone there?")

    assert port.transcript == [ErrorLine("the session has ended")]
    assert port.statuses == []


async def test_a_session_that_fails_is_shown_as_an_error_and_the_chat_goes_on(
    port: FakeChatAdapter,
) -> None:
    async with chatting(port):
        port.fails(ConnectionError("connection lost"))

    assert port.transcript == [
        ErrorLine("connection lost"),
        NoticeLine("Send another message to try again."),
    ]
    assert port.statuses == ["stopped"]


async def test_a_message_submitted_after_the_session_failed_has_it_run_again(
    port: FakeChatAdapter,
) -> None:
    async with chatting(port):
        port.fails(ConnectionError("connection lost"))
        await settled()
        port.submit("Try again")
        await settled()
        port.happens(AssistantMessage((TextPart("Back with you."),)))

    assert port.transcript[-1] == AssistantLine("Back with you.")
    assert port.reads_started == 2


async def test_the_transcript_opens_with_the_conversation_the_session_started_with() -> None:
    history: list[ContextEntry] = [
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
    port = FakeChatAdapter(history)

    async with chatting(port):
        pass

    assert port.transcript == [
        UserLine("What is in a.txt? [attachment]"),
        ThinkingLine("The file is the place to look."),
        AssistantLine("Let me look."),
        ToolCallLine("read_file", {"path": "a.txt"}),
        ToolResultLine("file contents"),
    ]


async def test_the_session_is_no_longer_read_once_the_user_quits(port: FakeChatAdapter) -> None:
    async with chatting(port):
        pass

    assert (port.reads_started, port.reads_finished) == (1, 1)

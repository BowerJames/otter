"""Behaviour of a realtime conversation used as a plain one, observed at a fake."""

from collections.abc import AsyncGenerator, Sequence
from types import TracebackType
from typing import Self

import pytest

from otter.conversation import realtime_as_conversation
from otter.core.domain.messages import AssistantMessage, TextPart, UserPart
from otter.realtime_conversation import RealtimeEvent, TextDelta, TurnDone


class FakeRealtimeConversation:
    """A test adapter for a realtime conversation: records what it is given, streams `events`.

    Setting `fail_with` makes generating raise it once the events have been streamed.
    """

    def __init__(self) -> None:
        self.user_messages: list[Sequence[UserPart]] = []
        self.tool_results: list[tuple[str, str]] = []
        self.events: list[RealtimeEvent] = []
        self.fail_with: Exception | None = None
        self.streams_closed = 0
        self.entered = 0
        self.left: list[BaseException | None] = []

    def add_user_message(self, content: Sequence[UserPart]) -> None:
        self.user_messages.append(content)

    def add_tool_result(self, tool_call_id: str, text: str) -> None:
        self.tool_results.append((tool_call_id, text))

    async def generate(self) -> AsyncGenerator[RealtimeEvent, None]:
        try:
            for event in self.events:
                yield event
            if self.fail_with:
                raise self.fail_with
        finally:
            self.streams_closed += 1

    async def __aenter__(self) -> Self:
        self.entered += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.left.append(exc)


@pytest.fixture
def fake_realtime() -> FakeRealtimeConversation:
    return FakeRealtimeConversation()


async def test_generating_returns_the_turn_the_realtime_conversation_ends_with(
    fake_realtime: FakeRealtimeConversation,
) -> None:
    fake_realtime.events = [
        TextDelta("Hi "),
        TextDelta("there"),
        TurnDone(AssistantMessage((TextPart("Hi there"),))),
    ]
    conversation = realtime_as_conversation(fake_realtime)

    assert await conversation.generate() == AssistantMessage((TextPart("Hi there"),))


async def test_generating_reads_the_realtime_stream_to_its_end(
    fake_realtime: FakeRealtimeConversation,
) -> None:
    fake_realtime.events = [TurnDone(AssistantMessage((TextPart("Hi"),)))]
    conversation = realtime_as_conversation(fake_realtime)

    await conversation.generate()

    assert fake_realtime.streams_closed == 1


async def test_generating_raises_what_the_realtime_conversation_raises(
    fake_realtime: FakeRealtimeConversation,
) -> None:
    fake_realtime.events = [TextDelta("Hi")]
    fake_realtime.fail_with = ConnectionError("connection lost")
    conversation = realtime_as_conversation(fake_realtime)

    with pytest.raises(ConnectionError, match=r"^connection lost$"):
        await conversation.generate()


def test_an_added_user_message_is_added_to_the_realtime_conversation(
    fake_realtime: FakeRealtimeConversation,
) -> None:
    conversation = realtime_as_conversation(fake_realtime)

    conversation.add_user_message([TextPart("Hello")])

    assert fake_realtime.user_messages == [[TextPart("Hello")]]


def test_an_added_tool_result_is_added_to_the_realtime_conversation(
    fake_realtime: FakeRealtimeConversation,
) -> None:
    conversation = realtime_as_conversation(fake_realtime)

    conversation.add_tool_result("call_1", "file contents")

    assert fake_realtime.tool_results == [("call_1", "file contents")]


async def test_entering_enters_the_realtime_conversation_and_gives_the_conversation(
    fake_realtime: FakeRealtimeConversation,
) -> None:
    conversation = realtime_as_conversation(fake_realtime)

    async with conversation as entered:
        assert entered is conversation
        assert (fake_realtime.entered, fake_realtime.left) == (1, [])


async def test_leaving_leaves_the_realtime_conversation(
    fake_realtime: FakeRealtimeConversation,
) -> None:
    async with realtime_as_conversation(fake_realtime):
        pass

    assert fake_realtime.left == [None]


async def test_leaving_because_of_an_error_leaves_the_realtime_conversation_with_the_error(
    fake_realtime: FakeRealtimeConversation,
) -> None:
    boom = KeyError("boom")

    with pytest.raises(KeyError, match=r"^'boom'$"):
        async with realtime_as_conversation(fake_realtime):
            raise boom

    assert fake_realtime.left == [boom]

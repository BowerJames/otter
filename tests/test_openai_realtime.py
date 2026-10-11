"""Behaviour of OpenAI realtime conversations, observed at a fake OpenAI realtime endpoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from openai.types.realtime import RealtimeClientEventParam, RealtimeServerEvent
from pydantic import TypeAdapter

from otter.domain.messages import AssistantMessage, TextPart, UserMessage
from otter.realtime_conversation import (
    RealtimeConnect,
    RealtimeConversation,
    TurnDone,
    create_openai_realtime_conversations,
)

_SERVER_EVENT: TypeAdapter[RealtimeServerEvent] = TypeAdapter(RealtimeServerEvent)

TURN_DONE = {
    "type": "response.done",
    "event_id": "event_1",
    "response": {
        "id": "resp_1",
        "object": "realtime.response",
        "status": "completed",
        "output": [
            {
                "id": "item_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "OK"}],
            }
        ],
    },
}


class FakeConnection:
    """One connection to the fake endpoint: `sent` is every event sent over it, in order."""

    def __init__(self) -> None:
        self.sent: list[Any] = []
        self._asked = False

    async def send(self, event: RealtimeClientEventParam) -> None:
        self.sent.append(event)
        self._asked = self._asked or event["type"] == "response.create"

    async def __aiter__(self) -> AsyncIterator[RealtimeServerEvent]:
        if self._asked:
            self._asked = False
            yield _SERVER_EVENT.validate_python(TURN_DONE)

    def session(self) -> Any:
        """What the endpoint was told of the session over this connection."""
        [update] = [event for event in self.sent if event["type"] == "session.update"]
        return update["session"]

    def items(self) -> list[Any]:
        """The conversation items sent over this connection, in order."""
        return [e["item"] for e in self.sent if e["type"] == "conversation.item.create"]


class FakeOpenAIRealtime:
    """A test adapter for the network: records the API key each connection was opened
    with and the model it was opened for, and answers every turn with the text "OK".
    """

    def __init__(self) -> None:
        self.opened: list[tuple[str, str]] = []
        self.connections: list[FakeConnection] = []

    def __call__(self, api_key: str) -> RealtimeConnect:
        @asynccontextmanager
        async def connect(model: str) -> AsyncIterator[FakeConnection]:
            self.opened.append((api_key, model))
            connection = FakeConnection()
            self.connections.append(connection)
            yield connection

        return connect


async def turn(conversation: RealtimeConversation) -> AssistantMessage:
    """Have the model take a whole turn and return it."""
    events = [event async for event in conversation.generate()]
    assert isinstance(events[-1], TurnDone)
    return events[-1].message


@pytest.fixture
def fake_openai() -> FakeOpenAIRealtime:
    return FakeOpenAIRealtime()


async def test_a_conversation_connects_for_its_model_with_the_api_key(
    fake_openai: FakeOpenAIRealtime,
) -> None:
    create_conversation = create_openai_realtime_conversations("openai-key", connector=fake_openai)
    conversation = create_conversation("gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])

    async with conversation:
        await turn(conversation)

    assert fake_openai.opened == [("openai-key", "gpt-realtime")]


async def test_a_conversation_does_not_connect_until_it_is_entered(
    fake_openai: FakeOpenAIRealtime,
) -> None:
    create_conversation = create_openai_realtime_conversations("openai-key", connector=fake_openai)

    conversation = create_conversation("gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])

    assert fake_openai.opened == []


async def test_a_conversation_writes_its_turns_as_text_when_no_voice_is_given(
    fake_openai: FakeOpenAIRealtime,
) -> None:
    create_conversation = create_openai_realtime_conversations("openai-key", connector=fake_openai)
    conversation = create_conversation("gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])

    async with conversation:
        await turn(conversation)

    [connection] = fake_openai.connections
    assert connection.session() == {"type": "realtime", "output_modalities": ["text"]}


async def test_a_conversation_speaks_its_turns_in_the_voice_given(
    fake_openai: FakeOpenAIRealtime,
) -> None:
    create_conversation = create_openai_realtime_conversations(
        "openai-key", voice="marin", connector=fake_openai
    )
    conversation = create_conversation("gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])

    async with conversation:
        await turn(conversation)

    [connection] = fake_openai.connections
    assert connection.session() == {
        "type": "realtime",
        "output_modalities": ["audio"],
        "audio": {"output": {"voice": "marin"}},
    }


async def test_a_conversation_starts_from_the_system_prompt_and_context_it_is_given(
    fake_openai: FakeOpenAIRealtime,
) -> None:
    create_conversation = create_openai_realtime_conversations("openai-key", connector=fake_openai)
    conversation = create_conversation(
        "gpt-realtime",
        system="Be brief.",
        context=[UserMessage((TextPart("Hello"),)), AssistantMessage((TextPart("Hi there"),))],
    )

    async with conversation:
        await turn(conversation)

    [connection] = fake_openai.connections
    assert connection.session()["instructions"] == "Be brief."
    assert connection.items() == [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Hello"}]},
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Hi there"}],
        },
    ]

"""Behaviour of the realtime adapter, driven through the model's port and observed at a fake
realtime endpoint.
"""

from collections.abc import AsyncIterator
from json import JSONDecodeError
from typing import Any

import pytest

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
    ToolSpec,
    UserMessage,
    UserPart,
)
from otter.core.model import ModelInput
from otter.infrastructure.adapters.model.openai_realtime import (
    ModelFailed,
    OpenAIRealtimeAdapter,
    TurnCutOff,
)

from .adapters import (
    FAILED,
    LOST,
    FakeRealtimeEndpoint,
    done,
    error,
    text_delta,
    text_item,
    tool_call_item,
    wav,
)

READ_FILE = ToolSpec(
    name="read_file",
    description="Read a file from disk.",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}},
)
HELLO = UserMessage((TextPart("Hello"),))
HELLO_ON_THE_WIRE = {
    "type": "message",
    "role": "user",
    "content": [{"type": "input_text", "text": "Hello"}],
}


def asking(*context: ContextEntry) -> ModelInput:
    return ModelInput(None, (), context)


@pytest.fixture
def endpoint() -> FakeRealtimeEndpoint:
    return FakeRealtimeEndpoint()


@pytest.fixture
async def adapter(endpoint: FakeRealtimeEndpoint) -> AsyncIterator[OpenAIRealtimeAdapter]:
    """An adapter for the model "gpt-realtime", opened, and closed after the test."""
    adapter = OpenAIRealtimeAdapter(endpoint, "gpt-realtime")
    await adapter.open()
    yield adapter
    await adapter.close()


async def test_opening_connects_for_the_model_it_was_made_for(
    endpoint: FakeRealtimeEndpoint,
) -> None:
    adapter = OpenAIRealtimeAdapter(endpoint, "gpt-realtime")
    assert endpoint.models == []

    await adapter.open()

    assert endpoint.models == ["gpt-realtime"]


async def test_closing_closes_the_connection(endpoint: FakeRealtimeEndpoint) -> None:
    adapter = OpenAIRealtimeAdapter(endpoint, "gpt-realtime")
    await adapter.open()

    await adapter.close()

    assert endpoint.connections[0].closed


async def test_opening_raises_what_connecting_raises(endpoint: FakeRealtimeEndpoint) -> None:
    endpoint.fail_to_connect = ConnectionRefusedError("refused")

    with pytest.raises(ConnectionRefusedError):
        await OpenAIRealtimeAdapter(endpoint, "gpt-realtime").open()


async def test_the_context_is_sent_and_then_a_response_is_asked_for(
    endpoint: FakeRealtimeEndpoint, adapter: OpenAIRealtimeAdapter
) -> None:
    await adapter.generate(asking(HELLO))

    [connection] = endpoint.connections
    assert connection.sent[1:] == [
        {"type": "conversation.item.create", "item": HELLO_ON_THE_WIRE},
        {"type": "response.create"},
    ]


async def test_the_endpoint_is_first_told_the_system_prompt_and_tools_and_asked_for_text(
    endpoint: FakeRealtimeEndpoint, adapter: OpenAIRealtimeAdapter
) -> None:
    await adapter.generate(ModelInput("Be brief.", (READ_FILE,), (HELLO,)))

    assert endpoint.connections[0].sent[0] == {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "output_modalities": ["text"],
            "instructions": "Be brief.",
            "tools": [
                {
                    "type": "function",
                    "name": "read_file",
                    "description": "Read a file from disk.",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                }
            ],
        },
    }


async def test_the_turn_is_what_the_model_wrote_once_it_is_done(
    endpoint: FakeRealtimeEndpoint, adapter: OpenAIRealtimeAdapter
) -> None:
    endpoint.turns = [[text_delta("Hi "), text_delta("there"), done(text_item("Hi there"))]]

    assert await adapter.generate(asking(HELLO)) == AssistantMessage((TextPart("Hi there"),))


async def test_the_turn_holds_the_tool_calls_the_model_asked_for(
    endpoint: FakeRealtimeEndpoint, adapter: OpenAIRealtimeAdapter
) -> None:
    endpoint.turns = [[done(tool_call_item("call_1", "read_file", '{"path": "a.txt"}'))]]

    assert await adapter.generate(asking(HELLO)) == AssistantMessage(
        (ToolCall("call_1", "read_file", {"path": "a.txt"}),)
    )


async def test_a_turn_going_on_from_the_last_sends_only_what_was_added_over_the_same_connection(
    endpoint: FakeRealtimeEndpoint, adapter: OpenAIRealtimeAdapter
) -> None:
    endpoint.turns = [[done(tool_call_item("call_1", "read_file", '{"path": "a.txt"}'))]]
    turn = await adapter.generate(ModelInput("Be brief.", (READ_FILE,), (HELLO,)))

    await adapter.generate(
        ModelInput("Be brief.", (READ_FILE,), (HELLO, turn, ToolResultMessage("call_1", "hi")))
    )

    [connection] = endpoint.connections
    assert len(connection.sessions()) == 1
    assert connection.items() == [
        HELLO_ON_THE_WIRE,
        {"type": "function_call_output", "call_id": "call_1", "output": "hi"},
    ]


async def test_a_context_that_does_not_go_on_from_the_last_is_sent_whole_over_a_new_connection(
    endpoint: FakeRealtimeEndpoint, adapter: OpenAIRealtimeAdapter
) -> None:
    await adapter.generate(asking(HELLO))
    other = UserMessage((TextPart("Something else"),))

    await adapter.generate(asking(other))

    [first, second] = endpoint.connections
    assert first.closed
    assert second.sessions() == [{"type": "realtime", "output_modalities": ["text"]}]
    assert second.items() == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Something else"}],
        }
    ]


async def test_a_new_system_prompt_is_told_to_the_endpoint_before_the_next_turn(
    endpoint: FakeRealtimeEndpoint, adapter: OpenAIRealtimeAdapter
) -> None:
    turn = await adapter.generate(ModelInput("Be brief.", (), (HELLO,)))

    await adapter.generate(ModelInput("Be thorough.", (), (HELLO, turn, HELLO)))

    [connection] = endpoint.connections
    assert [session.get("instructions") for session in connection.sessions()] == [
        "Be brief.",
        "Be thorough.",
    ]


async def test_an_assistant_turn_of_the_context_is_sent_without_its_thinking(
    endpoint: FakeRealtimeEndpoint, adapter: OpenAIRealtimeAdapter
) -> None:
    await adapter.generate(
        asking(
            HELLO,
            AssistantMessage(
                (
                    ThinkingPart("Look it up."),
                    TextPart("Let me look."),
                    ToolCall("call_1", "read_file", {"path": "a.txt"}),
                )
            ),
            ToolResultMessage("call_1", "hi"),
        )
    )

    assert endpoint.connections[0].items()[1:] == [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Let me look."}],
        },
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "read_file",
            "arguments": '{"path": "a.txt"}',
        },
        {"type": "function_call_output", "call_id": "call_1", "output": "hi"},
    ]


@pytest.mark.parametrize(
    "failing_turn, raised",
    [
        ([error("bad request")], ModelFailed),
        ([FAILED], ModelFailed),
        ([text_delta("I am")], TurnCutOff),
        ([LOST], ConnectionError),
        ([done(tool_call_item("call_1", "read_file", '{"path": '))], JSONDecodeError),
    ],
    ids=["error reported", "turn failed", "connection closed", "connection lost", "bad arguments"],
)
async def test_a_failed_turn_raises_and_the_next_sends_the_whole_context_over_a_new_connection(
    endpoint: FakeRealtimeEndpoint,
    adapter: OpenAIRealtimeAdapter,
    failing_turn: list[dict[str, Any]],
    raised: type[Exception],
) -> None:
    endpoint.turns = [[done(text_item("Hi there"))], failing_turn]
    turn = await adapter.generate(asking(HELLO))
    context = asking(HELLO, turn, UserMessage((TextPart("How are you?"),)))
    with pytest.raises(raised):
        await adapter.generate(context)

    await adapter.generate(context)

    [first, second] = endpoint.connections
    assert first.closed
    assert len(second.items()) == 3


async def test_a_failure_reported_by_the_endpoint_raises_with_its_reason(
    endpoint: FakeRealtimeEndpoint, adapter: OpenAIRealtimeAdapter
) -> None:
    endpoint.turns = [[FAILED]]

    with pytest.raises(ModelFailed, match="overloaded"):
        await adapter.generate(asking(HELLO))


@pytest.mark.parametrize(
    "part, sent",
    [
        (
            ImagePart(data="iVBORw==", media_type="image/png"),
            {"type": "input_image", "image_url": "data:image/png;base64,iVBORw=="},
        ),
        (
            ImageUrlPart("https://example.test/cat.png"),
            {
                "type": "input_text",
                "text": "[image omitted: this model takes images inline, not from a URL]",
            },
        ),
        (
            # "AQACAA==" is the base64 of the samples themselves, 01 00 02 00.
            AudioPart(data=wav(b"\x01\x00\x02\x00"), format="wav"),
            {"type": "input_audio", "audio": "AQACAA=="},
        ),
        (
            AudioPart(data=wav(b"\x01\x00\x02\x00", rate=44100), format="wav"),
            {
                "type": "input_text",
                "text": "[audio omitted: this model hears only 16-bit mono 24 kHz wav audio]",
            },
        ),
        (
            AudioPart(data=wav(b"\x01\x00\x02\x00", channels=2), format="wav"),
            {
                "type": "input_text",
                "text": "[audio omitted: this model hears only 16-bit mono 24 kHz wav audio]",
            },
        ),
        (
            AudioPart(data="SUQz", format="mp3"),
            {
                "type": "input_text",
                "text": "[audio omitted: this model hears only 16-bit mono 24 kHz wav audio]",
            },
        ),
        (
            AudioPart(data="not a wav file", format="wav"),
            {
                "type": "input_text",
                "text": "[audio omitted: this model hears only 16-bit mono 24 kHz wav audio]",
            },
        ),
    ],
    ids=["image", "image url", "wav", "wav 44.1 kHz", "wav stereo", "mp3", "unreadable wav"],
)
async def test_what_the_endpoint_takes_is_sent_and_a_note_goes_in_place_of_the_rest(
    endpoint: FakeRealtimeEndpoint,
    adapter: OpenAIRealtimeAdapter,
    part: UserPart,
    sent: dict[str, Any],
) -> None:
    await adapter.generate(asking(UserMessage((part,))))

    assert endpoint.connections[0].items()[0]["content"] == [sent]

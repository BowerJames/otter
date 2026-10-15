"""Behaviour of an OpenAI realtime conversation, observed at a fake realtime endpoint."""

import base64
import io
import wave
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from json import JSONDecodeError
from typing import Any

import pytest
from openai.types.realtime import RealtimeClientEventParam, RealtimeServerEvent
from pydantic import TypeAdapter

from otter.core.domain.messages import (
    AssistantMessage,
    AudioPart,
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
from otter.realtime_conversation import (
    AudioDelta,
    RealtimeConversation,
    TextDelta,
    TranscriptDelta,
    TurnDone,
    create_openai_realtime_conversation,
)

_SERVER_EVENT: TypeAdapter[RealtimeServerEvent] = TypeAdapter(RealtimeServerEvent)


def text_item(text: str) -> dict[str, Any]:
    """The wire form of an output item in which the model writes `text`."""
    return {
        "id": "item_1",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text}],
    }


def spoken_item(transcript: str) -> dict[str, Any]:
    """The wire form of an output item in which the model says `transcript` aloud."""
    return {
        "id": "item_1",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_audio", "transcript": transcript}],
    }


def tool_call_item(call_id: str, name: str, arguments: str) -> dict[str, Any]:
    """The wire form of an output item asking for one tool call; `arguments` is JSON text."""
    return {
        "id": f"item_{call_id}",
        "type": "function_call",
        "status": "completed",
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
    }


def delta(type: str, delta: str) -> dict[str, Any]:
    """The wire form of the event carrying the next piece of a turn, of the kind `type`."""
    return {
        "type": type,
        "event_id": "event_1",
        "response_id": "resp_1",
        "item_id": "item_1",
        "output_index": 0,
        "content_index": 0,
        "delta": delta,
    }


def done(*output: dict[str, Any], status: str = "completed", **more: Any) -> dict[str, Any]:
    """The wire form of the event that ends a turn whose output items are `output`."""
    return {
        "type": "response.done",
        "event_id": "event_1",
        "response": {
            "id": "resp_1",
            "object": "realtime.response",
            "status": status,
            "output": list(output),
            **more,
        },
    }


def error(message: str) -> dict[str, Any]:
    """The wire form of the event in which the endpoint reports that something failed."""
    return {
        "type": "error",
        "event_id": "event_1",
        "error": {"type": "invalid_request_error", "message": message},
    }


FAILED = done(
    status="failed",
    status_details={"type": "failed", "error": {"type": "server_error", "code": "overloaded"}},
)
LOST = {"type": "connection.lost"}


def wav(pcm: bytes, *, rate: int = 24000, channels: int = 1) -> str:
    """The base64 of a 16-bit wav file whose samples are `pcm`."""
    file = io.BytesIO()
    with wave.open(file, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(pcm)
    return base64.b64encode(file.getvalue()).decode()


class FakeConnection:
    """One connection to the fake endpoint: `sent` is every event sent over it, in order."""

    def __init__(self, endpoint: "FakeRealtimeEndpoint") -> None:
        self.sent: list[Any] = []
        self.closed = False
        self._endpoint = endpoint
        self._arriving: deque[dict[str, Any]] = deque()

    async def send(self, event: RealtimeClientEventParam) -> None:
        self.sent.append(event)
        if event["type"] == "response.create":
            self._arriving.extend(self._endpoint.next_turn())

    async def __aiter__(self) -> AsyncIterator[RealtimeServerEvent]:
        while self._arriving:
            event = self._arriving.popleft()
            if event["type"] == "connection.lost":
                raise ConnectionError("connection lost")
            yield _SERVER_EVENT.validate_python(event)

    def items(self) -> list[Any]:
        """The conversation items sent over this connection, in order."""
        return [e["item"] for e in self.sent if e["type"] == "conversation.item.create"]


class FakeRealtimeEndpoint:
    """A test adapter for the network: records each connection, answers with scripted turns.

    Each request for a response is answered with the next entry of `turns`, the server
    events of one turn; once they run out, with a plain text turn. A turn that ends
    without a `response.done` leaves the connection closed by the endpoint, and one
    holding `{"type": "connection.lost"}` breaks the connection at that point. While
    `fail_to_connect` is set, connecting raises it.
    """

    def __init__(self) -> None:
        self.models: list[str] = []
        self.connections: list[FakeConnection] = []
        self.turns: list[list[dict[str, Any]]] = []
        self.fail_to_connect: Exception | None = None

    @asynccontextmanager
    async def __call__(self, model: str) -> AsyncIterator[FakeConnection]:
        if self.fail_to_connect is not None:
            raise self.fail_to_connect
        self.models.append(model)
        connection = FakeConnection(self)
        self.connections.append(connection)
        try:
            yield connection
        finally:
            connection.closed = True

    def next_turn(self) -> list[dict[str, Any]]:
        return self.turns.pop(0) if self.turns else [done(text_item("OK"))]


async def turn(conversation: RealtimeConversation) -> AssistantMessage:
    """Have the model take a whole turn and return it."""
    events = [event async for event in conversation.generate()]
    assert isinstance(events[-1], TurnDone)
    return events[-1].message


READ_FILE = ToolSpec(
    name="read_file",
    description="Read a file from disk.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
)


@pytest.fixture
def fake_endpoint() -> FakeRealtimeEndpoint:
    return FakeRealtimeEndpoint()


type Start = Callable[..., Awaitable[RealtimeConversation]]


@pytest.fixture
async def start(fake_endpoint: FakeRealtimeEndpoint) -> AsyncIterator[Start]:
    """Starts a conversation at the fake endpoint and enters it; it is left after the test."""
    async with AsyncExitStack() as entered:

        async def start(**options: Any) -> RealtimeConversation:
            return await entered.enter_async_context(
                create_openai_realtime_conversation(fake_endpoint, **options)
            )

        yield start


async def test_generating_sends_the_added_user_message_to_the_configured_model(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    conversation = await start(model="gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])

    await turn(conversation)

    [connection] = fake_endpoint.connections
    assert fake_endpoint.models == ["gpt-realtime"]
    assert connection.items() == [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Hello"}]}
    ]
    assert connection.sent[-1] == {"type": "response.create"}


async def test_generating_ends_with_the_text_the_model_replied_with(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    fake_endpoint.turns = [[done(text_item("Hi there"))]]
    conversation = await start(model="gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])

    events = [event async for event in conversation.generate()]

    assert events == [TurnDone(AssistantMessage((TextPart("Hi there"),)))]


async def test_generating_yields_the_text_as_the_model_writes_it(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    fake_endpoint.turns = [
        [
            delta("response.output_text.delta", "Hi "),
            delta("response.output_text.delta", "there"),
            done(text_item("Hi there")),
        ]
    ]
    conversation = await start(model="gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])

    events = [event async for event in conversation.generate()]

    assert events[:-1] == [TextDelta("Hi "), TextDelta("there")]


async def test_generating_yields_what_the_model_says_as_sound_and_as_its_transcript(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    fake_endpoint.turns = [
        [
            delta("response.output_audio_transcript.delta", "Hi"),
            # "AAEC" is the base64 of the bytes 00 01 02.
            delta("response.output_audio.delta", "AAEC"),
            done(spoken_item("Hi")),
        ]
    ]
    conversation = await start(model="gpt-realtime", voice="marin")
    conversation.add_user_message([TextPart("Hello")])

    events = [event async for event in conversation.generate()]

    assert events[:-1] == [TranscriptDelta("Hi"), AudioDelta(b"\x00\x01\x02")]


async def test_a_spoken_turn_ends_with_its_transcript_as_text(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    fake_endpoint.turns = [[done(spoken_item("Hi there"))]]
    conversation = await start(model="gpt-realtime", voice="marin")
    conversation.add_user_message([TextPart("Hello")])

    assert await turn(conversation) == AssistantMessage((TextPart("Hi there"),))


async def test_generating_ends_with_the_tool_calls_the_model_asked_for(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    fake_endpoint.turns = [[done(tool_call_item("call_1", "read_file", '{"path": "a.txt"}'))]]
    conversation = await start(model="gpt-realtime", tools=[READ_FILE])
    conversation.add_user_message([TextPart("Read a.txt")])

    assert await turn(conversation) == AssistantMessage(
        (ToolCall(id="call_1", name="read_file", arguments={"path": "a.txt"}),)
    )


async def test_generating_first_tells_the_endpoint_the_system_prompt_and_the_tools(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    conversation = await start(model="gpt-realtime", system="Be brief.", tools=[READ_FILE])
    conversation.add_user_message([TextPart("Hello")])

    await turn(conversation)

    [connection] = fake_endpoint.connections
    assert connection.sent[0] == {
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
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                }
            ],
        },
    }


async def test_a_conversation_without_a_system_prompt_or_tools_asks_for_text_alone(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    conversation = await start(model="gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])

    await turn(conversation)

    [connection] = fake_endpoint.connections
    assert connection.sent[0] == {
        "type": "session.update",
        "session": {"type": "realtime", "output_modalities": ["text"]},
    }


async def test_a_conversation_given_a_voice_asks_the_model_to_speak_in_it(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    conversation = await start(model="gpt-realtime", voice="marin")
    conversation.add_user_message([TextPart("Hello")])

    await turn(conversation)

    [connection] = fake_endpoint.connections
    assert connection.sent[0] == {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "output_modalities": ["audio"],
            "audio": {"output": {"voice": "marin"}},
        },
    }


async def test_a_second_turn_sends_only_what_was_added_since_over_the_same_connection(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    conversation = await start(model="gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])
    await turn(conversation)
    conversation.add_user_message([TextPart("How are you?")])

    await turn(conversation)

    [connection] = fake_endpoint.connections
    assert [event["type"] for event in connection.sent] == [
        "session.update",
        "conversation.item.create",
        "response.create",
        "conversation.item.create",
        "response.create",
    ]
    assert connection.items()[1]["content"] == [{"type": "input_text", "text": "How are you?"}]


async def test_generating_sends_an_added_tool_result(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    fake_endpoint.turns = [[done(tool_call_item("call_1", "read_file", '{"path": "a.txt"}'))]]
    conversation = await start(model="gpt-realtime", tools=[READ_FILE])
    conversation.add_user_message([TextPart("Read a.txt")])
    await turn(conversation)
    conversation.add_tool_result("call_1", "file contents")

    await turn(conversation)

    [connection] = fake_endpoint.connections
    assert connection.items()[1:] == [
        {"type": "function_call_output", "call_id": "call_1", "output": "file contents"}
    ]


async def test_a_conversation_starts_from_the_context_it_is_given(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    conversation = await start(
        model="gpt-realtime",
        context=[
            UserMessage((TextPart("Read a.txt"),)),
            AssistantMessage(
                (
                    ThinkingPart("I should read it."),
                    TextPart("Reading."),
                    ToolCall(id="call_1", name="read_file", arguments={"path": "a.txt"}),
                )
            ),
            ToolResultMessage("call_1", "file contents"),
        ],
    )

    await turn(conversation)

    [connection] = fake_endpoint.connections
    assert connection.items() == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Read a.txt"}],
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Reading."}],
        },
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "read_file",
            "arguments": '{"path": "a.txt"}',
        },
        {"type": "function_call_output", "call_id": "call_1", "output": "file contents"},
    ]


async def test_generating_raises_when_the_endpoint_reports_an_error(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    fake_endpoint.turns = [[error("bad item")]]
    conversation = await start(model="gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])

    with pytest.raises(RuntimeError, match=r"^the model failed: bad item$"):
        await turn(conversation)


async def test_generating_raises_when_the_turn_ends_failed(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    fake_endpoint.turns = [[FAILED]]
    conversation = await start(model="gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])

    with pytest.raises(RuntimeError, match=r"^the model failed: overloaded$"):
        await turn(conversation)


async def test_generating_raises_when_the_connection_closes_before_the_turn_is_done(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    fake_endpoint.turns = [[delta("response.output_text.delta", "Hi")]]
    conversation = await start(model="gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])

    with pytest.raises(
        RuntimeError, match=r"^the connection closed before the model finished its turn$"
    ):
        await turn(conversation)


async def test_generating_raises_what_the_connection_raises(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    fake_endpoint.turns = [[LOST]]
    conversation = await start(model="gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])

    with pytest.raises(ConnectionError, match=r"^connection lost$"):
        await turn(conversation)


async def test_generating_raises_when_tool_arguments_are_not_json(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    fake_endpoint.turns = [[done(tool_call_item("call_1", "read_file", '{"path": '))]]
    conversation = await start(model="gpt-realtime", tools=[READ_FILE])
    conversation.add_user_message([TextPart("Read a.txt")])

    with pytest.raises(JSONDecodeError):
        await turn(conversation)


@pytest.mark.parametrize(
    "failing_turn",
    [
        [error("bad item")],
        [FAILED],
        [delta("response.output_text.delta", "I am")],
        [LOST],
        [done(tool_call_item("call_1", "read_file", '{"path": '))],
    ],
    ids=["error reported", "turn failed", "connection closed", "connection lost", "bad arguments"],
)
async def test_a_failed_turn_leaves_the_history_as_it_was_for_a_new_connection_to_be_sent(
    fake_endpoint: FakeRealtimeEndpoint, start: Start, failing_turn: list[dict[str, Any]]
) -> None:
    fake_endpoint.turns = [[done(text_item("Hi there"))], failing_turn]
    conversation = await start(model="gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])
    await turn(conversation)
    conversation.add_user_message([TextPart("How are you?")])
    with pytest.raises((RuntimeError, ConnectionError, JSONDecodeError)):
        await turn(conversation)

    await turn(conversation)

    [first, second] = fake_endpoint.connections
    assert first.closed
    assert second.items() == [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Hello"}]},
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Hi there"}],
        },
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "How are you?"}],
        },
    ]


async def test_closing_the_stream_early_abandons_the_turn_and_leaves_the_history_as_it_was(
    fake_endpoint: FakeRealtimeEndpoint, start: Start
) -> None:
    fake_endpoint.turns = [
        [delta("response.output_text.delta", "Hi "), done(text_item("Hi there"))]
    ]
    conversation = await start(model="gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])
    stream = conversation.generate()
    await anext(stream)

    await stream.aclose()

    await turn(conversation)
    [first, second] = fake_endpoint.connections
    assert first.closed
    assert second.items() == [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Hello"}]}
    ]


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
async def test_generating_sends_what_the_model_can_take_and_a_note_in_place_of_the_rest(
    fake_endpoint: FakeRealtimeEndpoint, start: Start, part: UserPart, sent: dict[str, Any]
) -> None:
    conversation = await start(model="gpt-realtime")
    conversation.add_user_message([part])

    await turn(conversation)

    [connection] = fake_endpoint.connections
    assert connection.items()[0]["content"] == [sent]


async def test_entering_a_conversation_gives_the_conversation(
    fake_endpoint: FakeRealtimeEndpoint,
) -> None:
    conversation = create_openai_realtime_conversation(fake_endpoint, model="gpt-realtime")

    async with conversation as entered:
        assert entered is conversation


async def test_a_conversation_does_not_connect_until_it_is_entered(
    fake_endpoint: FakeRealtimeEndpoint,
) -> None:
    conversation = create_openai_realtime_conversation(fake_endpoint, model="gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])

    assert fake_endpoint.connections == []


async def test_entering_a_conversation_connects_and_tells_the_endpoint_the_session(
    fake_endpoint: FakeRealtimeEndpoint,
) -> None:
    async with create_openai_realtime_conversation(fake_endpoint, model="gpt-realtime"):
        [connection] = fake_endpoint.connections
        assert fake_endpoint.models == ["gpt-realtime"]
        assert connection.sent == [
            {
                "type": "session.update",
                "session": {"type": "realtime", "output_modalities": ["text"]},
            }
        ]
        assert not connection.closed


async def test_leaving_a_conversation_closes_its_connection(
    fake_endpoint: FakeRealtimeEndpoint,
) -> None:
    async with create_openai_realtime_conversation(fake_endpoint, model="gpt-realtime"):
        pass

    [connection] = fake_endpoint.connections
    assert connection.closed


async def test_a_conversation_left_because_of_an_error_closes_its_connection_and_lets_the_error_out(
    fake_endpoint: FakeRealtimeEndpoint,
) -> None:
    with pytest.raises(KeyError, match=r"^'boom'$"):
        async with create_openai_realtime_conversation(fake_endpoint, model="gpt-realtime"):
            raise KeyError("boom")

    [connection] = fake_endpoint.connections
    assert connection.closed


async def test_entering_raises_what_connecting_raises(
    fake_endpoint: FakeRealtimeEndpoint,
) -> None:
    fake_endpoint.fail_to_connect = ConnectionError("no route")
    conversation = create_openai_realtime_conversation(fake_endpoint, model="gpt-realtime")

    with pytest.raises(ConnectionError, match=r"^no route$"):
        await conversation.__aenter__()


@pytest.mark.parametrize("left", [False, True], ids=["never entered", "left"])
async def test_generating_outside_the_conversation_raises_and_connects_to_nothing(
    fake_endpoint: FakeRealtimeEndpoint, left: bool
) -> None:
    conversation = create_openai_realtime_conversation(fake_endpoint, model="gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])
    if left:
        async with conversation:
            pass
    connections = len(fake_endpoint.connections)

    with pytest.raises(RuntimeError, match=r"^the conversation has not been entered$"):
        await turn(conversation)

    assert len(fake_endpoint.connections) == connections


async def test_a_conversation_entered_again_sends_the_whole_history_over_a_new_connection(
    fake_endpoint: FakeRealtimeEndpoint,
) -> None:
    fake_endpoint.turns = [[done(text_item("Hi there"))]]
    conversation = create_openai_realtime_conversation(fake_endpoint, model="gpt-realtime")
    conversation.add_user_message([TextPart("Hello")])
    async with conversation:
        await turn(conversation)
    conversation.add_user_message([TextPart("How are you?")])

    async with conversation:
        await turn(conversation)

    [_, second] = fake_endpoint.connections
    assert [item["role"] for item in second.items()] == ["user", "assistant", "user"]

"""Behaviour of ConversationAgentSession, observed at a fake conversation and its events."""

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence

import pytest

from otter.agent_session import AssistantTurn, Idle, SessionEvent, ToolResult, UserTurn
from otter.conversation import Conversation
from otter.conversation_agent_session import ConversationAgentSession
from otter.messages import (
    AssistantMessage,
    AudioPart,
    ImagePart,
    TextPart,
    ToolCall,
    ToolSpec,
    UserPart,
)


class FakeConversations:
    """A test adapter for the model: its one conversation records
    what joins its history and answers each `generate` with the next scripted turn.

    A scripted exception is raised in place of a turn.
    """

    def __init__(self) -> None:
        self.started: list[tuple[str | None, list[ToolSpec]]] = []
        self.history: list[object] = []
        self.script: list[AssistantMessage | Exception] = []

    def __call__(self, system: str | None, tools: Sequence[ToolSpec]) -> Conversation:
        self.started.append((system, list(tools)))
        return self

    def add_user_message(self, content: Sequence[UserPart]) -> None:
        self.history.append(("user", tuple(content)))

    def add_tool_result(self, tool_call_id: str, text: str) -> None:
        self.history.append(("tool", tool_call_id, text))

    async def generate(self) -> AssistantMessage:
        turn = self.script.pop(0)
        if isinstance(turn, Exception):
            raise turn
        self.history.append(turn)
        return turn


def says(text: str) -> AssistantMessage:
    return AssistantMessage(content=(TextPart(text),))


async def until_idle(stream: AsyncIterator[SessionEvent]) -> list[SessionEvent]:
    """Read events up to and including the next `Idle`."""
    events: list[SessionEvent] = []
    async for event in stream:
        events.append(event)
        if isinstance(event, Idle):
            break
    return events


READ_FILE = ToolSpec(
    name="read_file",
    description="Read a file",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}},
)


class FakeFiles:
    """A test adapter for a tool: records the arguments of each run, answers with fixed text."""

    name = "read_file"
    description = "Read a file"
    parameters: Mapping[str, object] = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    }

    def __init__(self) -> None:
        self.runs: list[Mapping[str, object]] = []

    async def execute(self, args: Mapping[str, object]) -> str:
        self.runs.append(args)
        return "file contents"


class UnreadableFiles(FakeFiles):
    async def execute(self, args: Mapping[str, object]) -> str:
        raise PermissionError("a.txt is not readable")


@pytest.fixture
def files() -> FakeFiles:
    return FakeFiles()


@pytest.fixture
def conversations() -> FakeConversations:
    return FakeConversations()


async def test_a_prompt_is_answered_by_the_model_and_the_session_comes_to_rest(
    conversations: FakeConversations,
) -> None:
    conversations.script = [says("Hi there")]
    session = ConversationAgentSession(conversations)
    session.prompt("Hello")

    events = await until_idle(session.stream())

    assert events == [
        UserTurn((TextPart("Hello"),)),
        AssistantTurn(says("Hi there")),
        Idle(),
    ]
    assert conversations.history == [("user", (TextPart("Hello"),)), says("Hi there")]


async def test_the_conversation_is_started_with_the_system_prompt_and_tool_specs(
    conversations: FakeConversations, files: FakeFiles
) -> None:
    ConversationAgentSession(conversations, system="Be brief.", tools=[files])

    assert conversations.started == [("Be brief.", [READ_FILE])]


async def test_a_prompt_carries_its_images_and_audio_after_its_text(
    conversations: FakeConversations,
) -> None:
    conversations.script = [says("Noted")]
    session = ConversationAgentSession(conversations)
    image = ImagePart(data="iVBORw==", media_type="image/png")
    clip = AudioPart(data="UklGRg==", format="wav")
    session.prompt("Look and listen", images=[image], audio=[clip])

    await until_idle(session.stream())

    assert conversations.history[0] == ("user", (TextPart("Look and listen"), image, clip))


async def test_a_tool_the_model_asks_for_is_run_and_its_result_goes_back_to_the_model(
    conversations: FakeConversations, files: FakeFiles
) -> None:
    asks = AssistantMessage(content=(ToolCall("call-1", "read_file", {"path": "a.txt"}),))
    conversations.script = [asks, says("It says hello")]
    session = ConversationAgentSession(conversations, tools=[files])
    session.prompt("What is in a.txt?")

    events = await until_idle(session.stream())

    assert files.runs == [{"path": "a.txt"}]
    assert events[1:] == [
        AssistantTurn(asks),
        ToolResult("call-1", "file contents"),
        AssistantTurn(says("It says hello")),
        Idle(),
    ]
    assert conversations.history[1:] == [
        asks,
        ("tool", "call-1", "file contents"),
        says("It says hello"),
    ]


async def test_a_prompt_made_while_the_session_is_at_rest_starts_the_model_again(
    conversations: FakeConversations,
) -> None:
    conversations.script = [says("Hi there"), says("Still here")]
    session = ConversationAgentSession(conversations)
    stream = session.stream()
    session.prompt("Hello")
    await until_idle(stream)

    session.prompt("Are you there?")
    events = await until_idle(stream)

    assert events == [
        UserTurn((TextPart("Are you there?"),)),
        AssistantTurn(says("Still here")),
        Idle(),
    ]


async def test_a_session_with_nothing_to_do_is_at_rest_from_the_start(
    conversations: FakeConversations,
) -> None:
    session = ConversationAgentSession(conversations)

    events = await until_idle(session.stream())

    assert events == [Idle()]
    assert conversations.history == []


async def test_a_prompt_made_while_the_model_is_working_joins_after_the_tool_results(
    conversations: FakeConversations, files: FakeFiles
) -> None:
    asks = AssistantMessage(
        content=(
            ToolCall("call-1", "read_file", {"path": "a.txt"}),
            ToolCall("call-2", "read_file", {"path": "b.txt"}),
        )
    )
    conversations.script = [asks, says("Done")]
    session = ConversationAgentSession(conversations, tools=[files])
    session.prompt("Read both files")
    stream = session.stream()
    while await anext(stream) != ToolResult("call-1", "file contents"):
        pass

    session.prompt("And be quick")
    await until_idle(stream)

    assert conversations.history == [
        ("user", (TextPart("Read both files"),)),
        asks,
        ("tool", "call-1", "file contents"),
        ("tool", "call-2", "file contents"),
        ("user", (TextPart("And be quick"),)),
        says("Done"),
    ]


async def test_ending_a_session_at_rest_ends_its_stream(
    conversations: FakeConversations,
) -> None:
    session = ConversationAgentSession(conversations)
    stream = session.stream()
    await until_idle(stream)

    session.end()

    assert [event async for event in stream] == []


async def test_ending_a_session_mid_turn_finishes_the_turn_and_goes_no_further(
    conversations: FakeConversations, files: FakeFiles
) -> None:
    asks = AssistantMessage(
        content=(
            ToolCall("call-1", "read_file", {"path": "a.txt"}),
            ToolCall("call-2", "read_file", {"path": "b.txt"}),
        )
    )
    conversations.script = [asks, says("Done")]
    session = ConversationAgentSession(conversations, tools=[files])
    session.prompt("Read both files")
    stream = session.stream()
    while await anext(stream) != AssistantTurn(asks):
        pass

    session.prompt("And be quick")
    session.end()

    assert [event async for event in stream] == [
        ToolResult("call-1", "file contents"),
        ToolResult("call-2", "file contents"),
    ]
    assert conversations.history == [
        ("user", (TextPart("Read both files"),)),
        asks,
        ("tool", "call-1", "file contents"),
        ("tool", "call-2", "file contents"),
    ]


async def test_an_ended_session_takes_no_more_prompts(
    conversations: FakeConversations,
) -> None:
    session = ConversationAgentSession(conversations)
    session.end()

    with pytest.raises(RuntimeError, match=r"^the session has ended$"):
        session.prompt("Hello")


async def test_a_failed_generate_propagates_and_streaming_again_retries_it(
    conversations: FakeConversations,
) -> None:
    conversations.script = [ConnectionError("no route to host"), says("Hi there")]
    session = ConversationAgentSession(conversations)
    session.prompt("Hello")
    with pytest.raises(ConnectionError, match=r"^no route to host$"):
        await until_idle(session.stream())

    events = await until_idle(session.stream())

    assert events == [AssistantTurn(says("Hi there")), Idle()]


async def test_a_failed_tool_propagates_and_ends_the_session(
    conversations: FakeConversations,
) -> None:
    asks = AssistantMessage(content=(ToolCall("call-1", "read_file", {"path": "a.txt"}),))
    conversations.script = [asks, says("Done")]
    session = ConversationAgentSession(conversations, tools=[UnreadableFiles()])
    session.prompt("What is in a.txt?")

    with pytest.raises(PermissionError, match=r"^a\.txt is not readable$"):
        await until_idle(session.stream())

    assert [event async for event in session.stream()] == []
    with pytest.raises(RuntimeError, match=r"^the session has ended$"):
        session.prompt("Try again")


async def test_a_session_has_one_stream_at_a_time(
    conversations: FakeConversations,
) -> None:
    session = ConversationAgentSession(conversations)
    first = session.stream()
    await until_idle(first)

    with pytest.raises(RuntimeError, match=r"^the session is already being streamed$"):
        await anext(session.stream())


async def test_waiting_for_idle_lasts_until_the_model_has_finished_its_work(
    conversations: FakeConversations, files: FakeFiles
) -> None:
    asks = AssistantMessage(content=(ToolCall("call-1", "read_file", {"path": "a.txt"}),))
    conversations.script = [asks, says("It says hello")]
    session = ConversationAgentSession(conversations, tools=[files])
    stream = session.stream()
    session.prompt("What is in a.txt?")
    waiting = asyncio.create_task(session.wait_for_idle())

    while await anext(stream) != ToolResult("call-1", "file contents"):
        pass
    await asyncio.sleep(0)
    assert not waiting.done()

    await until_idle(stream)
    await asyncio.wait_for(waiting, timeout=1)


async def test_waiting_for_idle_returns_at_once_for_a_session_with_nothing_to_do(
    conversations: FakeConversations,
) -> None:
    session = ConversationAgentSession(conversations)

    await asyncio.wait_for(session.wait_for_idle(), timeout=1)


async def test_waiting_for_idle_returns_when_the_session_ends(
    conversations: FakeConversations,
) -> None:
    session = ConversationAgentSession(conversations)
    session.prompt("Hello")
    waiting = asyncio.create_task(session.wait_for_idle())
    await asyncio.sleep(0)

    session.end()

    await asyncio.wait_for(waiting, timeout=1)

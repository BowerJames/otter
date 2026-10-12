"""Behaviour of a conversation agent session, observed at a fake conversation, a fake session
manager and its events.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import replace
from types import TracebackType
from typing import Self

import pytest

from otter.agent_session import (
    AgentSession,
    AgentTool,
    AssistantTurn,
    Deny,
    Idle,
    Plugin,
    SessionControls,
    SessionEvent,
    SessionSetup,
    ToolOutcome,
    ToolResult,
    UnknownTool,
    UserTurn,
    create_conversation_agent_session,
)
from otter.conversation import Conversation
from otter.domain.messages import (
    AssistantMessage,
    AudioPart,
    ContextEntry,
    ImagePart,
    TextPart,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
    UserPart,
)
from otter.model import Model
from otter.session_manager import SessionManager


class FakeConversations:
    """A test adapter for the model: its one conversation records what it was started with
    and what joins its history, and answers each `generate` with the next scripted turn.

    A scripted exception is raised in place of a turn. Setting `fail_to_leave` makes
    closing the conversation raise it.
    """

    def __init__(self) -> None:
        self.started: list[tuple[str | None, list[ToolSpec]]] = []
        self.contexts: list[list[ContextEntry]] = []
        self.history: list[object] = []
        self.script: list[AssistantMessage | Exception] = []
        self.entered = 0
        self.left = 0
        self.fail_to_enter: Exception | None = None
        self.fail_to_leave: Exception | None = None

    def __call__(
        self, system: str | None, tools: Sequence[ToolSpec], context: Sequence[ContextEntry]
    ) -> Conversation:
        self.started.append((system, list(tools)))
        self.contexts.append(list(context))
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

    async def __aenter__(self) -> Self:
        if self.fail_to_enter is not None:
            raise self.fail_to_enter
        self.entered += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.left += 1
        if self.fail_to_leave is not None:
            raise self.fail_to_leave


class FakeSessionManager:
    """A test adapter for the session manager: holds the entries it starts with and those
    appended to it.

    While `failing` is set, an append raises it and stores nothing.
    """

    def __init__(self, stored: Sequence[ContextEntry] = ()) -> None:
        self.stored = list(stored)
        self.failing: Exception | None = None

    def append(self, entry: ContextEntry) -> None:
        if self.failing is not None:
            raise self.failing
        self.stored.append(entry)

    def entries(self) -> Sequence[ContextEntry]:
        return tuple(self.stored)


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


async def start(
    model: Model,
    session_manager: SessionManager,
    *,
    system: str | None = None,
    tools: Sequence[AgentTool] = (),
    plugins: Sequence[Plugin] = (),
) -> AgentSession:
    """Make a session through the factory and enter it, so that its stream runs."""
    session = create_conversation_agent_session(
        model, session_manager, system=system, tools=tools, plugins=plugins
    )
    await session.__aenter__()
    return session


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


class StallingFiles(FakeFiles):
    """A test adapter for a tool: the second run never finishes, stalling the session mid-turn."""

    def __init__(self) -> None:
        super().__init__()
        self.second_run_started = asyncio.Event()

    async def execute(self, args: Mapping[str, object]) -> str:
        text = await super().execute(args)
        if len(self.runs) == 2:
            self.second_run_started.set()
            await asyncio.Event().wait()  # an event nothing ever sets: the run never finishes
        return text


@pytest.fixture
def files() -> FakeFiles:
    return FakeFiles()


@pytest.fixture
def conversations() -> FakeConversations:
    return FakeConversations()


@pytest.fixture
def manager() -> FakeSessionManager:
    return FakeSessionManager()


async def test_a_prompt_is_answered_by_the_model_and_the_session_comes_to_rest(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.script = [says("Hi there")]
    session = await start(conversations, manager)
    session.prompt("Hello")

    events = await until_idle(session.stream())

    assert events == [
        UserTurn((TextPart("Hello"),)),
        AssistantTurn(says("Hi there")),
        Idle(),
    ]
    assert conversations.history == [("user", (TextPart("Hello"),)), says("Hi there")]


async def test_the_conversation_is_started_with_the_system_prompt_and_tool_specs(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    await start(conversations, manager, system="Be brief.", tools=[files])

    assert conversations.started == [("Be brief.", [READ_FILE])]


async def test_a_prompt_carries_its_images_and_audio_after_its_text(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.script = [says("Noted")]
    session = await start(conversations, manager)
    image = ImagePart(data="iVBORw==", media_type="image/png")
    clip = AudioPart(data="UklGRg==", format="wav")
    session.prompt("Look and listen", images=[image], audio=[clip])

    await until_idle(session.stream())

    assert conversations.history[0] == ("user", (TextPart("Look and listen"), image, clip))


async def test_a_tool_the_model_asks_for_is_run_and_its_result_goes_back_to_the_model(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    asks = AssistantMessage(content=(ToolCall("call-1", "read_file", {"path": "a.txt"}),))
    conversations.script = [asks, says("It says hello")]
    session = await start(conversations, manager, tools=[files])
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
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.script = [says("Hi there"), says("Still here")]
    session = await start(conversations, manager)
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
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    session = await start(conversations, manager)

    events = await until_idle(session.stream())

    assert events == [Idle()]
    assert conversations.history == []


async def test_a_prompt_made_while_the_model_is_working_joins_after_the_tool_results(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    asks = AssistantMessage(
        content=(
            ToolCall("call-1", "read_file", {"path": "a.txt"}),
            ToolCall("call-2", "read_file", {"path": "b.txt"}),
        )
    )
    conversations.script = [asks, says("Done")]
    session = await start(conversations, manager, tools=[files])
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


async def test_queued_prompts_join_in_the_order_they_were_made(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    asks = AssistantMessage(content=(ToolCall("call-1", "read_file", {"path": "a.txt"}),))
    conversations.script = [asks, says("Done")]
    session = await start(conversations, manager, tools=[files])
    session.prompt("First")
    stream = session.stream()
    while await anext(stream) != AssistantTurn(asks):
        pass

    session.prompt("Second")
    session.prompt("Third")
    events = await until_idle(stream)

    assert events == [
        ToolResult("call-1", "file contents"),
        UserTurn((TextPart("Second"),)),
        UserTurn((TextPart("Third"),)),
        AssistantTurn(says("Done")),
        Idle(),
    ]
    assert conversations.history == [
        ("user", (TextPart("First"),)),
        asks,
        ("tool", "call-1", "file contents"),
        ("user", (TextPart("Second"),)),
        ("user", (TextPart("Third"),)),
        says("Done"),
    ]


async def test_ending_a_session_at_rest_ends_its_stream(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    session = await start(conversations, manager)
    stream = session.stream()
    await until_idle(stream)

    session.end()

    assert [event async for event in stream] == []


async def test_ending_a_session_mid_turn_finishes_the_turn_and_goes_no_further(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    asks = AssistantMessage(
        content=(
            ToolCall("call-1", "read_file", {"path": "a.txt"}),
            ToolCall("call-2", "read_file", {"path": "b.txt"}),
        )
    )
    conversations.script = [asks, says("Done")]
    session = await start(conversations, manager, tools=[files])
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


async def test_ending_an_ended_session_does_nothing(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.script = [says("Hi there")]
    session = await start(conversations, manager)
    session.prompt("Hello")
    stream = session.stream()
    await until_idle(stream)
    session.end()
    session.end()

    assert [event async for event in stream] == []
    with pytest.raises(RuntimeError, match=r"^the session has ended$"):
        session.prompt("Try again")


async def test_an_ended_session_takes_no_more_prompts(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    session = await start(conversations, manager)
    session.end()

    with pytest.raises(RuntimeError, match=r"^the session has ended$"):
        session.prompt("Hello")


async def test_a_failed_generate_propagates_and_streaming_again_retries_it(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.script = [ConnectionError("no route to host"), says("Hi there")]
    session = await start(conversations, manager)
    session.prompt("Hello")
    with pytest.raises(ConnectionError, match=r"^no route to host$"):
        await until_idle(session.stream())

    events = await until_idle(session.stream())

    assert events == [AssistantTurn(says("Hi there")), Idle()]


async def test_a_failed_tool_propagates_and_ends_the_session(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    asks = AssistantMessage(content=(ToolCall("call-1", "read_file", {"path": "a.txt"}),))
    conversations.script = [asks, says("Done")]
    session = await start(conversations, manager, tools=[UnreadableFiles()])
    session.prompt("What is in a.txt?")

    with pytest.raises(PermissionError, match=r"^a\.txt is not readable$"):
        await until_idle(session.stream())

    assert [event async for event in session.stream()] == []
    with pytest.raises(RuntimeError, match=r"^the session has ended$"):
        session.prompt("Try again")


async def test_a_stream_cancelled_part_way_through_a_turns_tool_calls_ends_the_session(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    asks = AssistantMessage(
        content=(
            ToolCall("call-1", "read_file", {"path": "a.txt"}),
            ToolCall("call-2", "read_file", {"path": "b.txt"}),
        )
    )
    conversations.script = [asks]
    files = StallingFiles()
    session = await start(conversations, manager, tools=[files])
    session.prompt("Read both files")

    async def read_the_stream() -> None:
        async for _ in session.stream():
            pass

    reading = asyncio.create_task(read_the_stream())
    await files.second_run_started.wait()
    reading.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reading

    with pytest.raises(RuntimeError, match=r"^the session has ended$"):
        session.prompt("Try again")


async def test_a_stream_abandoned_part_way_through_a_turns_tool_calls_ends_the_session(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    asks = AssistantMessage(
        content=(
            ToolCall("call-1", "read_file", {"path": "a.txt"}),
            ToolCall("call-2", "read_file", {"path": "b.txt"}),
        )
    )
    conversations.script = [asks]
    session = await start(conversations, manager, tools=[files])
    session.prompt("Read both files")
    stream = session.stream()
    while await anext(stream) != ToolResult("call-1", "file contents"):
        pass

    await stream.aclose()

    with pytest.raises(RuntimeError, match=r"^the session has ended$"):
        session.prompt("Try again")


async def test_a_session_has_one_stream_at_a_time(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    session = await start(conversations, manager)
    first = session.stream()
    await until_idle(first)

    with pytest.raises(RuntimeError, match=r"^the session is already being streamed$"):
        await anext(session.stream())


async def test_waiting_for_idle_lasts_until_the_model_has_finished_its_work(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    asks = AssistantMessage(content=(ToolCall("call-1", "read_file", {"path": "a.txt"}),))
    conversations.script = [asks, says("It says hello")]
    session = await start(conversations, manager, tools=[files])
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
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    session = await start(conversations, manager)

    await asyncio.wait_for(session.wait_for_idle(), timeout=1)


async def test_waiting_for_idle_returns_when_the_session_ends(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    session = await start(conversations, manager)
    session.prompt("Hello")
    waiting = asyncio.create_task(session.wait_for_idle())
    await asyncio.sleep(0)

    session.end()

    await asyncio.wait_for(waiting, timeout=1)


async def test_the_conversation_is_started_with_the_entries_the_session_manager_holds(
    conversations: FakeConversations,
) -> None:
    held: list[ContextEntry] = [UserMessage((TextPart("Hello"),)), says("Hi there")]

    await start(conversations, FakeSessionManager(held))

    assert conversations.contexts == [held]


async def test_everything_that_joins_the_conversation_is_appended_to_the_session_manager(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    asks = AssistantMessage(content=(ToolCall("call-1", "read_file", {"path": "a.txt"}),))
    conversations.script = [asks, says("It says hello")]
    session = await start(conversations, manager, tools=[files])
    session.prompt("What is in a.txt?")

    await until_idle(session.stream())

    assert manager.stored == [
        UserMessage((TextPart("What is in a.txt?"),)),
        asks,
        ToolResultMessage("call-1", "file contents"),
        says("It says hello"),
    ]


async def test_a_session_picks_up_after_the_entries_the_session_manager_holds(
    conversations: FakeConversations,
) -> None:
    held: list[ContextEntry] = [UserMessage((TextPart("Hello"),)), says("Hi there")]
    manager = FakeSessionManager(held)
    conversations.script = [says("Still here")]
    session = await start(conversations, manager)
    session.prompt("Are you there?")

    events = await until_idle(session.stream())

    assert events == [
        UserTurn((TextPart("Are you there?"),)),
        AssistantTurn(says("Still here")),
        Idle(),
    ]
    assert manager.stored == [
        *held,
        UserMessage((TextPart("Are you there?"),)),
        says("Still here"),
    ]


@pytest.mark.parametrize(
    "unanswered",
    [
        UserMessage((TextPart("Hello"),)),
        ToolResultMessage("call-1", "file contents"),
    ],
)
async def test_a_session_whose_context_ends_unanswered_has_the_model_answer_it(
    unanswered: ContextEntry, conversations: FakeConversations
) -> None:
    conversations.script = [says("Hi there")]
    session = await start(conversations, FakeSessionManager([unanswered]))

    events = await until_idle(session.stream())

    assert events == [AssistantTurn(says("Hi there")), Idle()]


async def test_a_session_whose_context_ends_with_the_models_turn_is_at_rest_from_the_start(
    conversations: FakeConversations,
) -> None:
    held: list[ContextEntry] = [UserMessage((TextPart("Hello"),)), says("Hi there")]
    session = await start(conversations, FakeSessionManager(held))

    events = await until_idle(session.stream())

    assert events == [Idle()]


async def test_a_prompt_the_session_manager_fails_to_take_propagates_and_streaming_again_retries(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.script = [says("Hi there")]
    session = await start(conversations, manager)
    session.prompt("Hello")
    manager.failing = OSError("disk full")
    with pytest.raises(OSError, match=r"^disk full$"):
        await until_idle(session.stream())
    assert conversations.history == []

    manager.failing = None
    events = await until_idle(session.stream())

    assert events == [
        UserTurn((TextPart("Hello"),)),
        AssistantTurn(says("Hi there")),
        Idle(),
    ]
    assert conversations.history == [("user", (TextPart("Hello"),)), says("Hi there")]


async def test_a_model_turn_the_session_manager_fails_to_take_propagates_and_ends_the_session(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.script = [says("Hi there")]
    session = await start(conversations, manager)
    stream = session.stream()
    session.prompt("Hello")
    assert await anext(stream) == UserTurn((TextPart("Hello"),))
    manager.failing = OSError("disk full")

    with pytest.raises(OSError, match=r"^disk full$"):
        await anext(stream)

    assert [event async for event in session.stream()] == []
    with pytest.raises(RuntimeError, match=r"^the session has ended$"):
        session.prompt("Try again")


async def test_a_tool_result_the_session_manager_fails_to_take_propagates_and_ends_the_session(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    asks = AssistantMessage(content=(ToolCall("call-1", "read_file", {"path": "a.txt"}),))
    conversations.script = [asks, says("Done")]
    session = await start(conversations, manager, tools=[files])
    stream = session.stream()
    session.prompt("What is in a.txt?")
    while await anext(stream) != AssistantTurn(asks):
        pass
    manager.failing = OSError("disk full")

    with pytest.raises(OSError, match=r"^disk full$"):
        await anext(stream)

    assert [event async for event in session.stream()] == []


async def test_entering_a_session_gives_the_session(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    session = create_conversation_agent_session(conversations, manager)

    async with session as entered:
        assert entered is session


async def test_a_session_enters_its_conversation_only_once_it_is_entered(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    session = create_conversation_agent_session(conversations, manager)
    assert conversations.entered == 0

    async with session:
        assert conversations.entered == 1


async def test_entering_a_session_raises_what_entering_its_conversation_raises(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.fail_to_enter = ConnectionError("no route")
    session = create_conversation_agent_session(conversations, manager)

    with pytest.raises(ConnectionError, match=r"^no route$"):
        async with session:
            pass

    assert conversations.left == 0


async def test_leaving_a_session_leaves_its_conversation(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    async with create_conversation_agent_session(conversations, manager):
        assert conversations.left == 0

    assert conversations.left == 1


async def test_leaving_a_session_ends_it(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    async with create_conversation_agent_session(conversations, manager) as session:
        stream = session.stream()
        await until_idle(stream)

    assert [event async for event in stream] == []
    with pytest.raises(RuntimeError, match=r"^the session has ended$"):
        session.prompt("Hello")


async def test_a_session_left_because_of_an_error_leaves_its_conversation_and_lets_the_error_out(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    with pytest.raises(KeyError, match=r"^'boom'$"):
        async with create_conversation_agent_session(conversations, manager):
            raise KeyError("boom")

    assert conversations.left == 1


async def test_a_conversation_that_fails_to_be_left_propagates_and_the_session_has_ended(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.fail_to_leave = ConnectionError("connection lost")
    session = create_conversation_agent_session(conversations, manager)

    with pytest.raises(ConnectionError, match=r"^connection lost$"):
        async with session:
            pass

    with pytest.raises(RuntimeError, match=r"^the session has ended$"):
        session.prompt("Hello")


async def test_a_stream_read_before_the_session_is_entered_yields_nothing_until_it_is(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.script = [says("Hi there")]
    session = create_conversation_agent_session(conversations, manager)
    session.prompt("Hello")
    reading = asyncio.create_task(until_idle(session.stream()))
    await asyncio.sleep(0)
    assert not reading.done()
    assert conversations.history == []

    async with session:
        events = await asyncio.wait_for(reading, timeout=1)

    assert events == [UserTurn((TextPart("Hello"),)), AssistantTurn(says("Hi there")), Idle()]


async def test_a_stream_waiting_for_the_session_to_be_entered_raises_what_entering_raises(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.fail_to_enter = ConnectionError("no route")
    session = create_conversation_agent_session(conversations, manager)
    reading = asyncio.create_task(until_idle(session.stream()))
    await asyncio.sleep(0)

    with pytest.raises(ConnectionError, match=r"^no route$"):
        await session.__aenter__()

    with pytest.raises(ConnectionError, match=r"^no route$"):
        await asyncio.wait_for(reading, timeout=1)


async def test_a_session_that_failed_to_be_entered_can_be_entered_and_streamed_again(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.script = [says("Hi there")]
    conversations.fail_to_enter = ConnectionError("no route")
    session = create_conversation_agent_session(conversations, manager)
    session.prompt("Hello")
    with pytest.raises(ConnectionError, match=r"^no route$"):
        await session.__aenter__()

    conversations.fail_to_enter = None
    async with session:
        events = await asyncio.wait_for(until_idle(session.stream()), timeout=1)

    assert events == [UserTurn((TextPart("Hello"),)), AssistantTurn(says("Hi there")), Idle()]


async def test_a_stream_waiting_for_a_session_that_is_ended_unentered_finishes(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    session = create_conversation_agent_session(conversations, manager)
    reading = asyncio.create_task(until_idle(session.stream()))
    await asyncio.sleep(0)

    session.end()

    assert await asyncio.wait_for(reading, timeout=1) == []


async def test_the_model_is_not_started_until_the_session_is_entered(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    session = create_conversation_agent_session(conversations, manager, system="Be brief.")
    assert conversations.started == []

    async with session:
        assert conversations.started == [("Be brief.", [])]


class Recorder(Plugin):
    """A test adapter for a plugin: records each hook it is asked at, under `name`, in a
    log it may share with other plugins.
    """

    def __init__(self, name: str = "plugin", log: list[object] | None = None) -> None:
        self.name = name
        self.log: list[object] = [] if log is None else log

    async def before_start(self, session: SessionControls, setup: SessionSetup) -> SessionSetup:
        self.log.append((self.name, "before_start", setup))
        return setup

    async def before_tool(self, session: SessionControls, call: ToolCall) -> Deny | None:
        self.log.append((self.name, "before_tool", call))
        return None

    async def after_tool(
        self, session: SessionControls, call: ToolCall, outcome: ToolOutcome
    ) -> ToolOutcome:
        self.log.append((self.name, "after_tool", call, outcome))
        return outcome

    async def before_idle(self, session: SessionControls) -> None:
        self.log.append((self.name, "before_idle"))

    async def on_event(self, session: SessionControls, event: SessionEvent) -> None:
        self.log.append((self.name, "on_event", event))

    async def after_end(self, session: SessionControls) -> None:
        self.log.append((self.name, "after_end"))


class Suffixing(Recorder):
    """A plugin that adds its name to the end of the system prompt."""

    async def before_start(self, session: SessionControls, setup: SessionSetup) -> SessionSetup:
        await super().before_start(session, setup)
        return replace(setup, system_prompt=f"{setup.system_prompt} {self.name}")


async def test_the_model_is_started_with_the_setup_a_plugin_returns_before_start(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    class AddsFiles(Plugin):
        async def before_start(self, session: SessionControls, setup: SessionSetup) -> SessionSetup:
            return SessionSetup("Be thorough.", (*setup.tools, files))

    await start(conversations, manager, system="Be brief.", plugins=[AddsFiles()])

    assert conversations.started == [("Be thorough.", [READ_FILE])]


async def test_a_tool_a_plugin_adds_before_start_is_run_when_the_model_asks_for_it(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    class AddsFiles(Plugin):
        async def before_start(self, session: SessionControls, setup: SessionSetup) -> SessionSetup:
            return replace(setup, tools=(*setup.tools, files))

    asks = AssistantMessage(content=(ToolCall("call-1", "read_file", {"path": "a.txt"}),))
    conversations.script = [asks, says("Done")]
    session = await start(conversations, manager, plugins=[AddsFiles()])
    session.prompt("What is in a.txt?")

    await until_idle(session.stream())

    assert files.runs == [{"path": "a.txt"}]


async def test_each_plugin_is_given_the_setup_the_plugin_before_it_returned(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    await start(
        conversations, manager, system="Be brief.", plugins=[Suffixing("a"), Suffixing("b")]
    )

    assert conversations.started == [("Be brief. a b", [])]


async def test_a_plugin_that_fails_before_start_propagates_and_the_model_is_not_started(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    class Failing(Plugin):
        async def before_start(self, session: SessionControls, setup: SessionSetup) -> SessionSetup:
            raise ValueError("no rules found")

    session = create_conversation_agent_session(conversations, manager, plugins=[Failing()])

    with pytest.raises(ValueError, match=r"^no rules found$"):
        await session.__aenter__()

    assert conversations.started == []


async def test_a_setup_with_two_tools_of_one_name_raises_and_the_model_is_not_started(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    session = create_conversation_agent_session(conversations, manager, tools=[files, FakeFiles()])

    with pytest.raises(ValueError, match=r"^two tools are named 'read_file'$"):
        await session.__aenter__()

    assert conversations.started == []


ASKS_FOR_A_FILE = AssistantMessage(content=(ToolCall("call-1", "read_file", {"path": "a.txt"}),))


class Denying(Recorder):
    """A plugin that denies every tool call, giving its name as the reason."""

    async def before_tool(self, session: SessionControls, call: ToolCall) -> Deny | None:
        await super().before_tool(session, call)
        return Deny(f"{self.name} says no")


class Reporting(Recorder):
    """A plugin that turns a tool call's error into text for the model."""

    async def after_tool(
        self, session: SessionControls, call: ToolCall, outcome: ToolOutcome
    ) -> ToolOutcome:
        await super().after_tool(session, call, outcome)
        if isinstance(outcome, Exception):
            return f"{call.name} failed: {outcome}"
        return outcome


async def test_a_tool_call_a_plugin_denies_is_not_run_and_the_model_is_shown_the_reason(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    conversations.script = [ASKS_FOR_A_FILE, says("Never mind")]
    session = await start(conversations, manager, tools=[files], plugins=[Denying("guard")])
    session.prompt("What is in a.txt?")

    events = await until_idle(session.stream())

    assert files.runs == []
    assert events[2] == ToolResult("call-1", "guard says no")
    assert conversations.history[2] == ("tool", "call-1", "guard says no")
    assert manager.stored[2] == ToolResultMessage("call-1", "guard says no")


async def test_every_plugin_is_asked_about_a_tool_call_and_the_model_is_shown_every_reason(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    conversations.script = [ASKS_FOR_A_FILE, says("Never mind")]
    watching = Recorder("watching")
    session = await start(
        conversations,
        manager,
        tools=[files],
        plugins=[Denying("first"), watching, Denying("second")],
    )
    session.prompt("What is in a.txt?")

    events = await until_idle(session.stream())

    assert events[2] == ToolResult("call-1", "first says no\nsecond says no")
    assert ("watching", "before_tool", ASKS_FOR_A_FILE.content[0]) in watching.log


async def test_a_denied_tool_call_is_not_put_to_plugins_after_the_tool(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    conversations.script = [ASKS_FOR_A_FILE, says("Never mind")]
    guard = Denying("guard")
    session = await start(conversations, manager, tools=[files], plugins=[guard])
    session.prompt("What is in a.txt?")

    await until_idle(session.stream())

    assert [entry for entry in guard.log if entry[1] == "after_tool"] == []  # type: ignore[index]


async def test_the_model_is_shown_the_text_a_plugin_returns_after_a_tool(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    class Shouting(Plugin):
        async def after_tool(
            self, session: SessionControls, call: ToolCall, outcome: ToolOutcome
        ) -> ToolOutcome:
            return str(outcome).upper()

    conversations.script = [ASKS_FOR_A_FILE, says("Loud")]
    session = await start(conversations, manager, tools=[files], plugins=[Shouting()])
    session.prompt("What is in a.txt?")

    events = await until_idle(session.stream())

    assert events[2] == ToolResult("call-1", "FILE CONTENTS")
    assert conversations.history[2] == ("tool", "call-1", "FILE CONTENTS")


async def test_each_plugin_is_given_the_outcome_the_plugin_before_it_returned(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    class Tagging(Plugin):
        def __init__(self, tag: str) -> None:
            self.tag = tag

        async def after_tool(
            self, session: SessionControls, call: ToolCall, outcome: ToolOutcome
        ) -> ToolOutcome:
            return f"{outcome} {self.tag}"

    conversations.script = [ASKS_FOR_A_FILE, says("Done")]
    session = await start(
        conversations, manager, tools=[files], plugins=[Tagging("a"), Tagging("b")]
    )
    session.prompt("What is in a.txt?")

    events = await until_idle(session.stream())

    assert events[2] == ToolResult("call-1", "file contents a b")


async def test_a_failed_tool_a_plugin_returns_text_for_goes_back_to_the_model_as_a_result(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.script = [ASKS_FOR_A_FILE, says("I could not read it")]
    session = await start(conversations, manager, tools=[UnreadableFiles()], plugins=[Reporting()])
    session.prompt("What is in a.txt?")

    events = await until_idle(session.stream())

    assert events[2:] == [
        ToolResult("call-1", "read_file failed: a.txt is not readable"),
        AssistantTurn(says("I could not read it")),
        Idle(),
    ]


async def test_a_failed_tool_no_plugin_returns_text_for_propagates_and_ends_the_session(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.script = [ASKS_FOR_A_FILE, says("Done")]
    watching = Recorder()
    session = await start(conversations, manager, tools=[UnreadableFiles()], plugins=[watching])
    session.prompt("What is in a.txt?")

    with pytest.raises(PermissionError, match=r"^a\.txt is not readable$"):
        await until_idle(session.stream())

    assert [type(entry[3]) for entry in watching.log if entry[1] == "after_tool"] == [  # type: ignore[index]
        PermissionError
    ]
    with pytest.raises(RuntimeError, match=r"^the session has ended$"):
        session.prompt("Try again")


async def test_an_error_a_plugin_returns_after_a_tool_propagates_and_ends_the_session(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    class Rejecting(Plugin):
        async def after_tool(
            self, session: SessionControls, call: ToolCall, outcome: ToolOutcome
        ) -> ToolOutcome:
            return ValueError("the result holds a secret")

    conversations.script = [ASKS_FOR_A_FILE, says("Done")]
    session = await start(conversations, manager, tools=[files], plugins=[Rejecting()])
    session.prompt("What is in a.txt?")

    with pytest.raises(ValueError, match=r"^the result holds a secret$"):
        await until_idle(session.stream())

    with pytest.raises(RuntimeError, match=r"^the session has ended$"):
        session.prompt("Try again")


async def test_a_call_to_a_tool_the_session_does_not_have_raises_unknown_tool(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.script = [ASKS_FOR_A_FILE, says("Done")]
    session = await start(conversations, manager)
    session.prompt("What is in a.txt?")

    with pytest.raises(UnknownTool, match=r"^the session has no tool named 'read_file'$") as raised:
        await until_idle(session.stream())

    assert raised.value.name == "read_file"


async def test_a_call_to_a_tool_the_session_does_not_have_is_put_to_plugins_as_unknown_tool(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.script = [ASKS_FOR_A_FILE, says("My mistake")]
    session = await start(conversations, manager, plugins=[Reporting()])
    session.prompt("What is in a.txt?")

    events = await until_idle(session.stream())

    assert events[2] == ToolResult(
        "call-1", "read_file failed: the session has no tool named 'read_file'"
    )


async def test_a_plugin_that_fails_after_a_tool_propagates_past_the_plugins_after_it(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    class Failing(Plugin):
        async def after_tool(
            self, session: SessionControls, call: ToolCall, outcome: ToolOutcome
        ) -> ToolOutcome:
            raise RuntimeError("plugin broke")

    conversations.script = [ASKS_FOR_A_FILE, says("Done")]
    reporting = Reporting()
    session = await start(conversations, manager, tools=[files], plugins=[Failing(), reporting])
    session.prompt("What is in a.txt?")

    with pytest.raises(RuntimeError, match=r"^plugin broke$"):
        await until_idle(session.stream())

    assert [entry for entry in reporting.log if entry[1] == "after_tool"] == []  # type: ignore[index]


async def test_a_prompt_a_plugin_makes_before_idle_keeps_the_session_from_coming_to_rest(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    class ChecksOnce(Plugin):
        def __init__(self) -> None:
            self.checked = False

        async def before_idle(self, session: SessionControls) -> None:
            if not self.checked:
                self.checked = True
                session.prompt("Check your work")

    conversations.script = [says("Done"), says("Checked")]
    session = await start(conversations, manager, plugins=[ChecksOnce()])
    session.prompt("Do the work")

    events = await until_idle(session.stream())

    assert events == [
        UserTurn((TextPart("Do the work"),)),
        AssistantTurn(says("Done")),
        UserTurn((TextPart("Check your work"),)),
        AssistantTurn(says("Checked")),
        Idle(),
    ]


async def test_waiting_for_idle_lasts_through_a_prompt_a_plugin_makes_before_idle(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    class ChecksOnce(Plugin):
        def __init__(self) -> None:
            self.checked = False

        async def before_idle(self, session: SessionControls) -> None:
            if not self.checked:
                self.checked = True
                session.prompt("Check your work")

    conversations.script = [says("Done"), says("Checked")]
    session = await start(conversations, manager, plugins=[ChecksOnce()])
    session.prompt("Do the work")
    stream = session.stream()
    waiting = asyncio.create_task(session.wait_for_idle())

    while await anext(stream) != UserTurn((TextPart("Check your work"),)):
        pass
    await asyncio.sleep(0)
    assert not waiting.done()

    await until_idle(stream)
    await asyncio.wait_for(waiting, timeout=1)


async def test_every_plugin_is_asked_before_idle_each_time_the_session_is_about_to_rest(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.script = [says("Hi there")]
    log: list[object] = []
    session = await start(conversations, manager, plugins=[Recorder("a", log), Recorder("b", log)])
    stream = session.stream()
    await until_idle(stream)
    session.prompt("Hello")
    await until_idle(stream)

    assert [entry for entry in log if entry[1] == "before_idle"] == [  # type: ignore[index]
        ("a", "before_idle"),
        ("b", "before_idle"),
        ("a", "before_idle"),
        ("b", "before_idle"),
    ]


async def test_a_plugin_that_ends_the_session_before_idle_finishes_the_stream(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    class OneShot(Plugin):
        async def before_idle(self, session: SessionControls) -> None:
            session.end()

    conversations.script = [says("Hi there")]
    session = await start(conversations, manager, plugins=[OneShot()])
    session.prompt("Hello")

    events = [event async for event in session.stream()]

    assert events == [UserTurn((TextPart("Hello"),)), AssistantTurn(says("Hi there"))]


async def test_a_plugin_that_fails_before_idle_propagates_and_streaming_again_asks_it_again(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    class FailsOnce(Plugin):
        def __init__(self) -> None:
            self.asked = 0

        async def before_idle(self, session: SessionControls) -> None:
            self.asked += 1
            if self.asked == 1:
                raise OSError("disk full")

    plugin = FailsOnce()
    session = await start(conversations, manager, plugins=[plugin])
    with pytest.raises(OSError, match=r"^disk full$"):
        await until_idle(session.stream())

    events = await until_idle(session.stream())

    assert events == [Idle()]
    assert plugin.asked == 2


async def test_a_plugin_is_told_each_event_before_the_stream_yields_it(
    conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    conversations.script = [ASKS_FOR_A_FILE, says("It says hello")]
    watching = Recorder()
    session = await start(conversations, manager, tools=[files], plugins=[watching])
    session.prompt("What is in a.txt?")
    stream = session.stream()

    first = await anext(stream)

    assert watching.log[-1] == ("plugin", "on_event", first)
    events = [first, *await until_idle(stream)]
    assert [entry[2] for entry in watching.log if entry[1] == "on_event"] == events  # type: ignore[index]
    assert events == [
        UserTurn((TextPart("What is in a.txt?"),)),
        AssistantTurn(ASKS_FOR_A_FILE),
        ToolResult("call-1", "file contents"),
        AssistantTurn(says("It says hello")),
        Idle(),
    ]


async def test_every_plugin_is_asked_after_end_when_the_session_is_left(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    log: list[object] = []
    session = create_conversation_agent_session(
        conversations, manager, plugins=[Recorder("a", log), Recorder("b", log)]
    )

    async with session:
        assert [entry for entry in log if entry[1] == "after_end"] == []  # type: ignore[index]

    assert log[-2:] == [("a", "after_end"), ("b", "after_end")]


async def test_a_plugin_that_fails_after_end_propagates_and_the_conversation_is_left(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    class Failing(Plugin):
        async def after_end(self, session: SessionControls) -> None:
            raise OSError("could not flush")

    session = create_conversation_agent_session(conversations, manager, plugins=[Failing()])

    with pytest.raises(OSError, match=r"^could not flush$"):
        async with session:
            pass

    assert conversations.left == 1


async def test_plugins_are_not_asked_after_end_by_a_session_that_failed_to_be_entered(
    conversations: FakeConversations, manager: FakeSessionManager
) -> None:
    conversations.fail_to_enter = ConnectionError("no route")
    watching = Recorder()
    session = create_conversation_agent_session(conversations, manager, plugins=[watching])

    with pytest.raises(ConnectionError, match=r"^no route$"):
        async with session:
            pass

    assert [entry for entry in watching.log if entry[1] == "after_end"] == []  # type: ignore[index]


class ActingAt(Plugin):
    """A test adapter for a plugin: does `act` to the session the first time it is asked at
    the hook named `hook`, and otherwise leaves everything as it is.
    """

    def __init__(self, hook: str, act: Callable[[SessionControls], None]) -> None:
        self.hook = hook
        self.act = act
        self.acted = False

    def _asked_at(self, hook: str, session: SessionControls) -> None:
        if hook == self.hook and not self.acted:
            self.acted = True
            self.act(session)

    async def before_start(self, session: SessionControls, setup: SessionSetup) -> SessionSetup:
        self._asked_at("before_start", session)
        return setup

    async def before_tool(self, session: SessionControls, call: ToolCall) -> Deny | None:
        self._asked_at("before_tool", session)
        return None

    async def after_tool(
        self, session: SessionControls, call: ToolCall, outcome: ToolOutcome
    ) -> ToolOutcome:
        self._asked_at("after_tool", session)
        return outcome

    async def before_idle(self, session: SessionControls) -> None:
        self._asked_at("before_idle", session)

    async def on_event(self, session: SessionControls, event: SessionEvent) -> None:
        self._asked_at("on_event", session)

    async def after_end(self, session: SessionControls) -> None:
        self._asked_at("after_end", session)


def fail(session: SessionControls) -> None:
    raise OSError("plugin broke")


HOOKS_WHILE_RUNNING = [
    "before_start",
    "before_tool",
    "after_tool",
    "before_idle",
    "on_event",
]


@pytest.mark.parametrize("hook", [*HOOKS_WHILE_RUNNING, "after_end"])
async def test_a_plugin_that_fails_at_a_hook_propagates_from_the_session(
    hook: str, conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    conversations.script = [ASKS_FOR_A_FILE, says("It says hello")]
    session = create_conversation_agent_session(
        conversations, manager, tools=[files], plugins=[ActingAt(hook, fail)]
    )
    session.prompt("What is in a.txt?")

    with pytest.raises(OSError, match=r"^plugin broke$"):
        async with session:
            await until_idle(session.stream())


@pytest.mark.parametrize("hook", ["before_tool", "after_tool", "on_event"])
async def test_a_plugin_that_fails_part_way_through_a_turns_tool_calls_ends_the_session(
    hook: str, conversations: FakeConversations, files: FakeFiles
) -> None:
    # The context ends unanswered, so the first thing to happen is the model's turn.
    manager = FakeSessionManager([UserMessage((TextPart("What is in a.txt?"),))])
    conversations.script = [ASKS_FOR_A_FILE, says("It says hello")]
    session = await start(conversations, manager, tools=[files], plugins=[ActingAt(hook, fail)])

    with pytest.raises(OSError, match=r"^plugin broke$"):
        await until_idle(session.stream())

    with pytest.raises(RuntimeError, match=r"^the session has ended$"):
        session.prompt("Try again")


@pytest.mark.parametrize("hook", HOOKS_WHILE_RUNNING)
async def test_a_prompt_a_plugin_makes_at_a_hook_joins_the_conversation(
    hook: str, conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    def prompt(session: SessionControls) -> None:
        session.prompt("And be quick")

    conversations.script = [ASKS_FOR_A_FILE, says("It says hello"), says("Quickly")]
    session = await start(conversations, manager, tools=[files], plugins=[ActingAt(hook, prompt)])
    session.prompt("What is in a.txt?")

    await asyncio.wait_for(until_idle(session.stream()), timeout=1)

    joined = [entry for entry in conversations.history if isinstance(entry, tuple)]
    assert joined.count(("user", (TextPart("And be quick"),))) == 1
    assert manager.stored.count(UserMessage((TextPart("And be quick"),))) == 1


@pytest.mark.parametrize("hook", HOOKS_WHILE_RUNNING)
async def test_a_plugin_that_ends_the_session_at_a_hook_finishes_the_stream(
    hook: str, conversations: FakeConversations, manager: FakeSessionManager, files: FakeFiles
) -> None:
    def end(session: SessionControls) -> None:
        session.end()

    conversations.script = [ASKS_FOR_A_FILE, says("It says hello")]
    session = create_conversation_agent_session(
        conversations, manager, tools=[files], plugins=[ActingAt(hook, end)]
    )
    session.prompt("What is in a.txt?")
    await session.__aenter__()

    async def read_to_the_end() -> list[SessionEvent]:
        return [event async for event in session.stream()]

    events = await asyncio.wait_for(read_to_the_end(), timeout=1)

    assert Idle() not in events
    with pytest.raises(RuntimeError, match=r"^the session has ended$"):
        session.prompt("Try again")

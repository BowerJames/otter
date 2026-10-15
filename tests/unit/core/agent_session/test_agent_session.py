"""Behaviour of an agent session, observed at a fake port and through its events."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from otter.core.agent_session import (
    AgentSession,
    AgentSessionImpl,
    AlreadyStreaming,
    Idle,
    SessionControls,
    SessionEnded,
    SessionEvent,
)
from otter.core.domain.messages import (
    AssistantMessage,
    AudioPart,
    ContextEntry,
    ImagePart,
    TextPart,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

from .adapters import FakeAgentSessionAdapter


def says(text: str) -> AssistantMessage:
    return AssistantMessage((TextPart(text),))


def user(text: str) -> UserMessage:
    return UserMessage((TextPart(text),))


ASKS_FOR_A_FILE = AssistantMessage((ToolCall("call-1", "read_file", {"path": "a.txt"}),))
ASKS_FOR_TWO_FILES = AssistantMessage(
    (
        ToolCall("call-1", "read_file", {"path": "a.txt"}),
        ToolCall("call-2", "read_file", {"path": "b.txt"}),
    )
)
FIRST_RESULT = ToolResultMessage("call-1", "file contents")
SECOND_RESULT = ToolResultMessage("call-2", "file contents")


def setup(port: FakeAgentSessionAdapter) -> AgentSession:
    return AgentSessionImpl(port)


async def entered(port: FakeAgentSessionAdapter) -> AgentSession:
    """A session in the world `port` gives it, entered so that its stream runs."""
    session = setup(port)
    await session.__aenter__()
    return session


async def until_idle(stream: AsyncIterator[SessionEvent]) -> list[SessionEvent]:
    """Read events up to and including the next `Idle`."""
    events: list[SessionEvent] = []
    async for event in stream:
        events.append(event)
        if isinstance(event, Idle):
            break
    return events


async def to_the_end(session: AgentSession) -> list[SessionEvent]:
    return [event async for event in session.stream()]


@pytest.fixture
def port() -> FakeAgentSessionAdapter:
    return FakeAgentSessionAdapter()


# The conversation


async def test_a_prompt_is_answered_by_the_model_and_the_session_comes_to_rest(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [says("Hi there")]
    session = await entered(port)
    session.prompt("Hello")

    events = await until_idle(session.stream())

    assert events == [user("Hello"), says("Hi there"), Idle()]


async def test_the_model_is_shown_the_whole_conversation_each_turn(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [ASKS_FOR_A_FILE, says("It says hello")]
    session = await entered(port)
    session.prompt("What is in a.txt?")

    await until_idle(session.stream())

    assert port.shown == [
        (user("What is in a.txt?"),),
        (user("What is in a.txt?"), ASKS_FOR_A_FILE, FIRST_RESULT),
    ]


async def test_a_prompt_carries_its_images_and_audio_after_its_text(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [says("Noted")]
    session = await entered(port)
    image = ImagePart(data="iVBORw==", media_type="image/png")
    clip = AudioPart(data="UklGRg==", format="wav")
    session.prompt("Look and listen", images=[image], audio=[clip])

    events = await until_idle(session.stream())

    assert events[0] == UserMessage((TextPart("Look and listen"), image, clip))


async def test_each_tool_call_the_model_asks_for_is_run_in_order_and_its_result_joins(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [ASKS_FOR_TWO_FILES, says("Both say hello")]
    session = await entered(port)
    session.prompt("Read both files")

    events = await until_idle(session.stream())

    assert port.runs == list(ASKS_FOR_TWO_FILES.content)
    assert events[1:] == [
        ASKS_FOR_TWO_FILES,
        FIRST_RESULT,
        SECOND_RESULT,
        says("Both say hello"),
        Idle(),
    ]


async def test_a_prompt_made_while_the_session_is_at_rest_starts_the_model_again(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [says("Hi there"), says("Still here")]
    session = await entered(port)
    stream = session.stream()
    session.prompt("Hello")
    await until_idle(stream)

    session.prompt("Are you there?")

    assert await until_idle(stream) == [user("Are you there?"), says("Still here"), Idle()]


async def test_a_session_with_nothing_to_do_is_at_rest_from_the_start(
    port: FakeAgentSessionAdapter,
) -> None:
    session = await entered(port)

    assert await until_idle(session.stream()) == [Idle()]
    assert port.shown == []


async def test_a_prompt_made_while_the_model_is_working_joins_after_the_tool_results(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [ASKS_FOR_TWO_FILES, says("Done")]
    session = await entered(port)
    session.prompt("Read both files")
    stream = session.stream()
    while await anext(stream) != FIRST_RESULT:
        pass

    session.prompt("And be quick")

    assert await until_idle(stream) == [SECOND_RESULT, user("And be quick"), says("Done"), Idle()]


async def test_queued_prompts_join_in_the_order_they_were_made(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [ASKS_FOR_A_FILE, says("Done")]
    session = await entered(port)
    session.prompt("First")
    stream = session.stream()
    while await anext(stream) != ASKS_FOR_A_FILE:
        pass

    session.prompt("Second")
    session.prompt("Third")

    assert await until_idle(stream) == [
        FIRST_RESULT,
        user("Second"),
        user("Third"),
        says("Done"),
        Idle(),
    ]


# History


async def test_the_history_is_empty_until_the_session_is_entered(
    port: FakeAgentSessionAdapter,
) -> None:
    port.context = [user("Hello"), says("Hi there")]

    assert list(setup(port).history()) == []


async def test_the_history_is_the_context_the_session_started_with_then_what_joined(
    port: FakeAgentSessionAdapter,
) -> None:
    port.context = [user("Hello"), says("Hi there")]
    port.script = [says("Still here")]
    session = await entered(port)
    session.prompt("Are you there?")

    await until_idle(session.stream())

    assert list(session.history()) == [
        user("Hello"),
        says("Hi there"),
        user("Are you there?"),
        says("Still here"),
    ]


async def test_a_history_already_returned_is_unchanged_as_more_joins(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [says("Hi there")]
    session = await entered(port)
    before = session.history()
    session.prompt("Hello")

    await until_idle(session.stream())

    assert list(before) == []


# The context the session starts with, and what it records


async def test_the_model_is_shown_the_context_the_session_started_with(
    port: FakeAgentSessionAdapter,
) -> None:
    port.context = [user("Hello"), says("Hi there")]
    port.script = [says("Still here")]
    session = await entered(port)
    session.prompt("Are you there?")

    await until_idle(session.stream())

    assert port.shown == [(user("Hello"), says("Hi there"), user("Are you there?"))]


async def test_everything_that_joins_the_conversation_is_recorded(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [ASKS_FOR_A_FILE, says("It says hello")]
    session = await entered(port)
    session.prompt("What is in a.txt?")

    await until_idle(session.stream())

    assert port.recorded == [
        user("What is in a.txt?"),
        ASKS_FOR_A_FILE,
        FIRST_RESULT,
        says("It says hello"),
    ]


@pytest.mark.parametrize("unanswered", [user("Hello"), FIRST_RESULT])
async def test_a_session_whose_context_ends_unanswered_has_the_model_answer_it(
    unanswered: ContextEntry, port: FakeAgentSessionAdapter
) -> None:
    port.context = [unanswered]
    port.script = [says("Hi there")]
    session = await entered(port)

    assert await until_idle(session.stream()) == [says("Hi there"), Idle()]


async def test_a_session_whose_context_ends_with_the_models_turn_is_at_rest_from_the_start(
    port: FakeAgentSessionAdapter,
) -> None:
    port.context = [user("Hello"), says("Hi there")]
    session = await entered(port)

    assert await until_idle(session.stream()) == [Idle()]


# Ending


async def test_ending_a_session_at_rest_ends_its_stream(port: FakeAgentSessionAdapter) -> None:
    session = await entered(port)
    stream = session.stream()
    await until_idle(stream)

    session.end()

    assert [event async for event in stream] == []


async def test_ending_a_session_mid_turn_finishes_the_turn_and_goes_no_further(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [ASKS_FOR_TWO_FILES, says("Done")]
    session = await entered(port)
    session.prompt("Read both files")
    stream = session.stream()
    while await anext(stream) != ASKS_FOR_TWO_FILES:
        pass

    session.prompt("And be quick")
    session.end()

    assert [event async for event in stream] == [FIRST_RESULT, SECOND_RESULT]
    assert len(port.shown) == 1


async def test_ending_an_ended_session_does_nothing(port: FakeAgentSessionAdapter) -> None:
    session = await entered(port)
    stream = session.stream()
    await until_idle(stream)
    session.end()

    session.end()

    assert [event async for event in stream] == []


async def test_an_ended_session_takes_no_more_prompts(port: FakeAgentSessionAdapter) -> None:
    session = await entered(port)
    session.end()

    with pytest.raises(SessionEnded, match=r"^the session has ended$"):
        session.prompt("Hello")


# Failures


async def test_a_failed_turn_propagates_and_streaming_again_retries_it(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [ConnectionError("no route to host"), says("Hi there")]
    session = await entered(port)
    session.prompt("Hello")
    with pytest.raises(ConnectionError, match=r"^no route to host$"):
        await until_idle(session.stream())

    assert await until_idle(session.stream()) == [says("Hi there"), Idle()]
    assert port.shown == [(user("Hello"),), (user("Hello"),)]


async def test_a_failed_tool_call_propagates_and_ends_the_session(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [ASKS_FOR_A_FILE, says("Done")]
    port.tool_outcome = PermissionError("a.txt is not readable")
    session = await entered(port)
    session.prompt("What is in a.txt?")

    with pytest.raises(PermissionError, match=r"^a\.txt is not readable$"):
        await until_idle(session.stream())

    assert await to_the_end(session) == []
    with pytest.raises(SessionEnded):
        session.prompt("Try again")


async def test_a_stream_cancelled_part_way_through_a_turns_tool_calls_ends_the_session(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [ASKS_FOR_TWO_FILES]
    port.stalling_at_run = 2
    session = await entered(port)
    session.prompt("Read both files")
    reading = asyncio.create_task(to_the_end(session))
    await port.stalled.wait()

    reading.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reading

    with pytest.raises(SessionEnded):
        session.prompt("Try again")


async def test_a_stream_abandoned_part_way_through_a_turns_tool_calls_ends_the_session(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [ASKS_FOR_TWO_FILES]
    session = await entered(port)
    session.prompt("Read both files")
    stream = session.stream()
    while await anext(stream) != FIRST_RESULT:
        pass

    await stream.aclose()

    with pytest.raises(SessionEnded):
        session.prompt("Try again")


async def test_a_stream_abandoned_once_the_turn_is_answered_leaves_the_session_as_it_was(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [ASKS_FOR_A_FILE, says("Done")]
    session = await entered(port)
    session.prompt("What is in a.txt?")
    stream = session.stream()
    while await anext(stream) != FIRST_RESULT:
        pass

    await stream.aclose()

    assert await until_idle(session.stream()) == [says("Done"), Idle()]


async def test_a_session_has_one_stream_at_a_time(port: FakeAgentSessionAdapter) -> None:
    session = await entered(port)
    first = session.stream()
    await until_idle(first)

    with pytest.raises(AlreadyStreaming, match=r"^the session is already being streamed$"):
        await anext(session.stream())


async def test_a_prompt_that_cannot_be_recorded_propagates_and_stays_queued(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [says("Hi there")]
    session = await entered(port)
    session.prompt("Hello")
    port.failing_to_record = OSError("disk full")
    with pytest.raises(OSError, match=r"^disk full$"):
        await until_idle(session.stream())
    assert port.shown == []

    port.failing_to_record = None

    assert await until_idle(session.stream()) == [user("Hello"), says("Hi there"), Idle()]


async def test_a_turn_that_cannot_be_recorded_propagates_and_ends_the_session(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [says("Hi there")]
    session = await entered(port)
    stream = session.stream()
    session.prompt("Hello")
    assert await anext(stream) == user("Hello")
    port.failing_to_record = OSError("disk full")

    with pytest.raises(OSError, match=r"^disk full$"):
        await anext(stream)

    assert await to_the_end(session) == []
    assert list(session.history()) == [user("Hello")]


async def test_a_tool_result_that_cannot_be_recorded_propagates_and_ends_the_session(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [ASKS_FOR_A_FILE, says("Done")]
    session = await entered(port)
    stream = session.stream()
    session.prompt("What is in a.txt?")
    while await anext(stream) != ASKS_FOR_A_FILE:
        pass
    port.failing_to_record = OSError("disk full")

    with pytest.raises(OSError, match=r"^disk full$"):
        await anext(stream)

    assert await to_the_end(session) == []


# Waiting for idle


async def test_waiting_for_idle_lasts_until_the_model_has_finished_its_work(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [ASKS_FOR_A_FILE, says("It says hello")]
    session = await entered(port)
    stream = session.stream()
    session.prompt("What is in a.txt?")
    waiting = asyncio.create_task(session.wait_for_idle())

    while await anext(stream) != FIRST_RESULT:
        pass
    await asyncio.sleep(0)
    assert not waiting.done()

    await until_idle(stream)
    await asyncio.wait_for(waiting, timeout=1)


async def test_waiting_for_idle_returns_at_once_for_a_session_with_nothing_to_do(
    port: FakeAgentSessionAdapter,
) -> None:
    session = await entered(port)

    await asyncio.wait_for(session.wait_for_idle(), timeout=1)


async def test_waiting_for_idle_returns_when_the_session_ends(
    port: FakeAgentSessionAdapter,
) -> None:
    session = await entered(port)
    session.prompt("Hello")
    waiting = asyncio.create_task(session.wait_for_idle())
    await asyncio.sleep(0)

    session.end()

    await asyncio.wait_for(waiting, timeout=1)


# Entering and leaving


async def test_entering_a_session_gives_the_session(port: FakeAgentSessionAdapter) -> None:
    session = setup(port)

    async with session as entered_session:
        assert entered_session is session


async def test_the_port_is_started_only_once_the_session_is_entered(
    port: FakeAgentSessionAdapter,
) -> None:
    session = setup(port)
    assert port.calls == []

    async with session:
        assert port.calls == ["start"]


async def test_entering_raises_what_starting_raises_and_nothing_is_stopped(
    port: FakeAgentSessionAdapter,
) -> None:
    port.fail_to_start = ConnectionError("no route")

    with pytest.raises(ConnectionError, match=r"^no route$"):
        async with setup(port):
            pass

    assert port.calls == []


async def test_leaving_a_session_stops_the_port(port: FakeAgentSessionAdapter) -> None:
    async with setup(port):
        pass

    assert port.calls == ["start", "stop"]


async def test_leaving_a_session_ends_it(port: FakeAgentSessionAdapter) -> None:
    async with setup(port) as session:
        stream = session.stream()
        await until_idle(stream)

    assert [event async for event in stream] == []
    with pytest.raises(SessionEnded):
        session.prompt("Hello")


async def test_a_session_left_because_of_an_error_stops_the_port_and_lets_the_error_out(
    port: FakeAgentSessionAdapter,
) -> None:
    with pytest.raises(KeyError, match=r"^'boom'$"):
        async with setup(port):
            raise KeyError("boom")

    assert port.calls == ["start", "stop"]


async def test_a_port_that_fails_to_stop_propagates_and_the_session_has_ended(
    port: FakeAgentSessionAdapter,
) -> None:
    port.fail_to_stop = ConnectionError("connection lost")
    session = setup(port)

    with pytest.raises(ConnectionError, match=r"^connection lost$"):
        async with session:
            pass

    with pytest.raises(SessionEnded):
        session.prompt("Hello")


async def test_a_stream_read_before_the_session_is_entered_yields_nothing_until_it_is(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [says("Hi there")]
    session = setup(port)
    session.prompt("Hello")
    reading = asyncio.create_task(until_idle(session.stream()))
    await asyncio.sleep(0)
    assert not reading.done()

    async with session:
        events = await asyncio.wait_for(reading, timeout=1)

    assert events == [user("Hello"), says("Hi there"), Idle()]


async def test_a_stream_waiting_for_the_session_to_be_entered_raises_what_entering_raises(
    port: FakeAgentSessionAdapter,
) -> None:
    port.fail_to_start = ConnectionError("no route")
    session = setup(port)
    reading = asyncio.create_task(until_idle(session.stream()))
    await asyncio.sleep(0)

    with pytest.raises(ConnectionError, match=r"^no route$"):
        await session.__aenter__()

    with pytest.raises(ConnectionError, match=r"^no route$"):
        await asyncio.wait_for(reading, timeout=1)


async def test_a_session_that_failed_to_be_entered_can_be_entered_and_streamed_again(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [says("Hi there")]
    port.fail_to_start = ConnectionError("no route")
    session = setup(port)
    session.prompt("Hello")
    with pytest.raises(ConnectionError):
        await session.__aenter__()

    port.fail_to_start = None
    async with session:
        events = await asyncio.wait_for(until_idle(session.stream()), timeout=1)

    assert events == [user("Hello"), says("Hi there"), Idle()]


async def test_a_stream_waiting_for_a_session_that_is_ended_unentered_finishes(
    port: FakeAgentSessionAdapter,
) -> None:
    session = setup(port)
    reading = asyncio.create_task(until_idle(session.stream()))
    await asyncio.sleep(0)

    session.end()

    assert await asyncio.wait_for(reading, timeout=1) == []


# The port's hooks


async def test_the_port_is_told_each_event_before_the_stream_yields_it(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [ASKS_FOR_A_FILE, says("It says hello")]
    session = await entered(port)
    session.prompt("What is in a.txt?")
    stream = session.stream()

    first = await anext(stream)

    assert port.told == [first]
    assert [first, *await until_idle(stream)] == port.told


async def test_the_port_is_asked_before_idle_each_time_the_session_is_about_to_rest(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [says("Hi there")]
    session = await entered(port)
    stream = session.stream()
    await until_idle(stream)
    session.prompt("Hello")

    await until_idle(stream)

    assert port.calls == ["start", "before_idle", "before_idle"]


async def test_a_prompt_made_before_idle_keeps_the_session_from_coming_to_rest(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [says("Done"), says("Checked")]
    port.acting_at["before_idle"] = lambda session: session.prompt("Check your work")
    session = await entered(port)
    session.prompt("Do the work")

    assert await until_idle(session.stream()) == [
        user("Do the work"),
        says("Done"),
        user("Check your work"),
        says("Checked"),
        Idle(),
    ]


async def test_waiting_for_idle_lasts_through_a_prompt_made_before_idle(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [says("Done"), says("Checked")]
    port.acting_at["before_idle"] = lambda session: session.prompt("Check your work")
    session = await entered(port)
    session.prompt("Do the work")
    stream = session.stream()
    waiting = asyncio.create_task(session.wait_for_idle())

    while await anext(stream) != user("Check your work"):
        pass
    await asyncio.sleep(0)
    assert not waiting.done()

    await until_idle(stream)
    await asyncio.wait_for(waiting, timeout=1)


async def test_a_session_ended_before_idle_finishes_its_stream(
    port: FakeAgentSessionAdapter,
) -> None:
    port.script = [says("Hi there")]
    port.acting_at["before_idle"] = lambda session: session.end()
    session = await entered(port)
    session.prompt("Hello")

    assert await to_the_end(session) == [user("Hello"), says("Hi there")]


async def test_a_failure_before_idle_propagates_and_streaming_again_asks_again(
    port: FakeAgentSessionAdapter,
) -> None:
    port.fail_before_idle = OSError("disk full")
    session = await entered(port)
    with pytest.raises(OSError, match=r"^disk full$"):
        await until_idle(session.stream())

    assert await until_idle(session.stream()) == [Idle()]
    assert port.calls == ["start", "before_idle", "before_idle"]


def end(session: SessionControls) -> None:
    session.end()


def prompt(session: SessionControls) -> None:
    session.prompt("And be quick")


@pytest.mark.parametrize("call", ["start", "generate", "run_tool", "record", "on_event"])
async def test_a_prompt_the_port_makes_joins_the_conversation_once(
    call: str, port: FakeAgentSessionAdapter
) -> None:
    port.script = [ASKS_FOR_A_FILE, says("It says hello"), says("Quickly")]
    port.acting_at[call] = prompt
    session = setup(port)
    session.prompt("What is in a.txt?")
    await session.__aenter__()

    await asyncio.wait_for(until_idle(session.stream()), timeout=1)

    assert list(session.history()).count(user("And be quick")) == 1


@pytest.mark.parametrize("call", ["start", "generate", "run_tool", "record", "on_event"])
async def test_a_session_the_port_ends_finishes_its_stream(
    call: str, port: FakeAgentSessionAdapter
) -> None:
    port.script = [ASKS_FOR_A_FILE, says("It says hello")]
    port.acting_at[call] = end
    session = setup(port)
    session.prompt("What is in a.txt?")
    await session.__aenter__()

    events = await asyncio.wait_for(to_the_end(session), timeout=1)

    assert Idle() not in events

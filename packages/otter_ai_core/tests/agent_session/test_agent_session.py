import asyncio

import pytest

from otter_ai_core.agent import AgentLoopExhausted, AgentLoopOptions, AgentOptions
from otter_ai_core.agent.types import AgentEnd, AgentStart, AgentTurnEnd, AgentTurnStart
from otter_ai_core.agent_session import AgentSession
from otter_ai_core.fake_model import FakeModel, FakeModelExhausted
from otter_ai_core.in_memory_auth_storage import InMemoryAuthStorage
from otter_ai_core.in_memory_session import InMemorySessionManager
from otter_ai_core.model_registry import ModelRegistry
from otter_ai_core.types import (
    AssistantMessage,
    SessionMessage,
    TextContent,
    ToolResultMessage,
    UserMessage,
)

from .support import (
    LifecycleSpySessionManager,
    RecordingModelFactory,
    StubProvider,
    _assistant_message,
    _final_response,
    _make_session,
    _noop_tool,
    _tool_call_response,
    _user_message,
    collect_events,
    seeded_storage,
)


async def test_construction_performs_no_io() -> None:
    registry = ModelRegistry({}, InMemoryAuthStorage())
    manager = InMemorySessionManager()

    session = AgentSession(
        model="gpt-4o",
        provider="openai",
        system_prompt="system",
        tools=[],
        session_manager=manager,
        model_registry=registry,
    )

    assert session.is_idle() is True
    assert manager.entries == ()


async def test_enter_replays_session_messages_into_factory_prefix() -> None:
    manager = InMemorySessionManager()
    history: list[SessionMessage] = [_user_message("earlier"), _assistant_message()]
    async with manager:
        for message in history:
            await manager.append_message(message)

    factory = RecordingModelFactory([_final_response("hello")])
    session = await _make_session(manager, factory)

    async with session:
        pass

    assert factory.calls == [("system", [], history)]


async def test_enter_failure_unwinds_partial_entry() -> None:
    spy = LifecycleSpySessionManager(InMemorySessionManager())
    factory = RecordingModelFactory([_final_response("hello")])
    registry = ModelRegistry({}, InMemoryAuthStorage())

    session = AgentSession(
        model="gpt-4o",
        provider="openai",
        system_prompt="system",
        tools=[],
        session_manager=spy,
        model_registry=registry,
    )

    with pytest.raises(KeyError):
        await session.__aenter__()

    assert factory.calls == []
    assert spy.entered == 1
    assert spy.exited == 1


async def test_enter_failure_after_model_entry_unwinds_everything() -> None:
    spy = LifecycleSpySessionManager(InMemorySessionManager())
    factory = RecordingModelFactory([_final_response("hello")])
    registry = ModelRegistry(
        {"openai": StubProvider(factory)},
        await seeded_storage(("openai", "sk-key")),
    )

    session = AgentSession(
        model="gpt-4o",
        provider="openai",
        system_prompt="system",
        tools=[_noop_tool(), _noop_tool()],  # duplicate names: Agent rejects
        session_manager=spy,
        model_registry=registry,
    )

    with pytest.raises(ValueError):
        await session.__aenter__()

    assert len(factory.calls) == 1  # factory called, model entered...
    assert spy.entered == 1
    assert spy.exited == 1  # ...and the unwind closed the manager


async def test_prompt_runs_records_and_yields_run_events() -> None:
    manager = InMemorySessionManager()
    reply = _final_response("hello there")
    factory = RecordingModelFactory([reply])
    session = await _make_session(manager, factory)

    async with session:
        session.prompt("hi")
        consumer = asyncio.create_task(collect_events(session))
        await session.wait_for_idle()

    events = await consumer

    kinds = [type(event) for event in events]
    assert kinds == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentEnd,
    ]

    user_event = events[2]
    assistant_event = events[3]
    assert isinstance(user_event, UserMessage)
    assert isinstance(user_event.content[0], TextContent)
    assert user_event.content[0].text == "hi"
    assert assistant_event == reply
    turn_end = events[4]
    assert isinstance(turn_end, AgentTurnEnd)
    assert turn_end.termination == "final_response"
    run_end = events[5]
    assert isinstance(run_end, AgentEnd)
    assert run_end.messages == [user_event, assistant_event]

    assert factory.calls == [("system", [], [])]
    assert list(manager.entries) == [user_event, assistant_event]


async def test_prompt_while_active_queues_steering() -> None:
    manager = InMemorySessionManager()
    factory = RecordingModelFactory([_tool_call_response(), _final_response("done")])
    session = await _make_session(manager, factory)

    async with session:
        session.prompt("start")
        assert session.is_idle() is False
        session.prompt("course correction")
        consumer = asyncio.create_task(collect_events(session))
        await session.wait_for_idle()
    events = await consumer

    kinds = [type(event) for event in events]
    assert kinds.count(AgentStart) == 1
    assert kinds.count(AgentEnd) == 1

    user_texts = [event.content[0].text for event in events if isinstance(event, UserMessage)]
    assert user_texts == ["start", "course correction"]

    assert [type(message) for message in manager.entries] == [
        UserMessage,
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        AssistantMessage,
    ]


async def test_channel_spans_multiple_runs() -> None:
    manager = InMemorySessionManager()
    factory = RecordingModelFactory([_final_response("first"), _final_response("second")])
    session = await _make_session(manager, factory)

    async with session:
        consumer = asyncio.create_task(collect_events(session))

        session.prompt("one")
        await session.wait_for_idle()
        assert session.is_idle() is True

        session.prompt("two")
        await session.wait_for_idle()

    events = await consumer

    starts = [index for index, event in enumerate(events) if type(event) is AgentStart]
    ends = [index for index, event in enumerate(events) if type(event) is AgentEnd]
    assert len(starts) == 2
    assert len(ends) == 2
    assert starts[0] < ends[0] < starts[1] < ends[1]

    first_end = events[ends[0]]
    second_end = events[ends[1]]
    assert isinstance(first_end, AgentEnd)
    assert isinstance(second_end, AgentEnd)
    assert len(first_end.messages) == 2
    assert len(second_end.messages) == 2

    assert [type(message) for message in manager.entries] == [
        UserMessage,
        AssistantMessage,
        UserMessage,
        AssistantMessage,
    ]


async def test_operations_are_gated_by_session_lifecycle() -> None:
    manager = InMemorySessionManager()
    factory = RecordingModelFactory([_final_response("hello")])
    session = await _make_session(manager, factory)

    with pytest.raises(RuntimeError):
        session.prompt("too early")
    with pytest.raises(RuntimeError):
        session.__aiter__()

    async with session:
        session.__aiter__()
        with pytest.raises(RuntimeError):
            session.__aiter__()

    with pytest.raises(RuntimeError):
        session.prompt("too late")
    with pytest.raises(RuntimeError):
        session.__aiter__()
    with pytest.raises(RuntimeError):
        await session.__aenter__()


async def test_run_completes_and_records_without_consumer() -> None:
    manager = InMemorySessionManager()
    reply = _final_response("recorded anyway")
    factory = RecordingModelFactory([reply])
    session = await _make_session(manager, factory)

    async with session:
        session.prompt("nobody is listening")
        await session.wait_for_idle()

    entries = list(manager.entries)
    assert [type(message) for message in entries] == [UserMessage, AssistantMessage]
    assert entries[1] == reply
    assert factory.calls == [("system", [], [])]


async def test_exit_waits_for_active_run_and_delivers_remaining_events() -> None:
    manager = InMemorySessionManager()
    gate = asyncio.Event()
    reply = _final_response("slow reply")
    model = FakeModel([reply], generation_gate=gate)
    factory = RecordingModelFactory.for_model(model)
    session = await _make_session(manager, factory)

    async with session:
        session.prompt("slow")
        assert session.is_idle() is False
        consumer = asyncio.create_task(collect_events(session))
        asyncio.get_running_loop().call_later(0, gate.set)

    events = await consumer

    kinds = [type(event) for event in events]
    assert kinds == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentEnd,
    ]
    user_event = events[2]
    assert isinstance(user_event, UserMessage)
    run_end = events[-1]
    assert isinstance(run_end, AgentEnd)
    assert run_end.messages[0] == user_event
    assert run_end.messages[-1] == reply
    assert run_end.termination == "final_response"
    assert len(run_end.turns) == 1
    assert [type(message) for message in manager.entries] == [UserMessage, AssistantMessage]


async def test_exit_does_not_suppress_exceptions() -> None:
    spy = LifecycleSpySessionManager(InMemorySessionManager())
    factory = RecordingModelFactory([_final_response("unseen")])
    session = await _make_session(spy, factory)

    with pytest.raises(ZeroDivisionError):
        async with session:
            session.prompt("hi")
            await session.wait_for_idle()
            raise ZeroDivisionError

    assert spy.exited == 1


async def test_resumed_session_appends_after_the_replayed_prefix() -> None:
    manager = InMemorySessionManager()
    prefix: list[SessionMessage] = [_user_message("earlier"), _assistant_message()]
    async with manager:
        for message in prefix:
            await manager.append_message(message)

    factory = RecordingModelFactory([_final_response("continued")])
    session = await _make_session(manager, factory)

    async with session:
        session.prompt("and now")
        consumer = asyncio.create_task(collect_events(session))
        await session.wait_for_idle()
    await consumer

    assert factory.calls == [("system", [], prefix)]

    entries = list(manager.entries)
    assert entries[:2] == prefix
    resumed_user = entries[2]
    assert isinstance(resumed_user, UserMessage)
    assert resumed_user.content[0].text == "and now"
    assert entries[3] == _final_response("continued")
    assert len(entries) == 4


async def test_agent_options_are_passed_through_to_the_agent() -> None:
    manager = InMemorySessionManager()
    options = AgentOptions(agent_loop_options=AgentLoopOptions(max_generations=1))
    factory = RecordingModelFactory([_tool_call_response("noop")])
    registry = ModelRegistry(
        {"openai": StubProvider(factory)},
        await seeded_storage(("openai", "sk-key")),
    )
    session = AgentSession(
        model="gpt-4o",
        provider="openai",
        system_prompt="system",
        tools=[_noop_tool()],
        session_manager=manager,
        model_registry=registry,
        agent_options=options,
    )

    async with session:
        session.prompt("one generation only")
        with pytest.raises(AgentLoopExhausted):
            await collect_events(session)


async def test_run_error_propagates_to_channel_and_poisons_the_session() -> None:
    spy = LifecycleSpySessionManager(InMemorySessionManager())
    factory = RecordingModelFactory([])
    session = await _make_session(spy, factory)

    async with session:
        session.prompt("doomed")
        consumer = asyncio.create_task(collect_events(session))
        with pytest.raises(FakeModelExhausted):
            await consumer

        assert session.is_idle() is False
        with pytest.raises(RuntimeError):
            session.prompt("nope")

    assert spy.exited == 1
    assert [type(message) for message in spy.entries] == [UserMessage]

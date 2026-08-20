import asyncio
from types import TracebackType
from typing import Any, Self

import pytest
from pydantic import BaseModel

from otter_ai_core.agent import (
    Agent,
    AgentEnd,
    AgentEvent,
    AgentHooks,
    AgentLoopExhausted,
    AgentLoopOptions,
    AgentLoopStranded,
    AgentOptions,
    AgentStart,
    AgentStream,
    AgentTurnEnd,
    AgentTurnStart,
    ToolCallDecision,
)
from otter_ai_core.agent_tool import AgentToolResult, create_agent_tool
from otter_ai_core.conversation import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from otter_ai_core.model import Model
from otter_ai_core.model.fake import FakeModel


def response(
    id: str, text: str | None = None, tool_calls: list[ToolCall] | None = None
) -> AssistantMessage:
    calls = tool_calls or []
    if text is None and not calls:
        raise ValueError("scripted response needs text or tool_calls")
    return AssistantMessage(
        id=id,
        content=[TextContent(text=text)] if text is not None else [],
        tool_calls=calls,
        stop_reason="tool_call" if calls else "final_response",
    )


async def collect(stream: AgentStream) -> list[AgentEvent]:
    return [event async for event in stream]


class PingParams(BaseModel):
    pass


class ScheduleParams(BaseModel):
    pass


class StopParams(BaseModel):
    stop: bool


class SpinParams(BaseModel):
    pass


class GuardedParams(BaseModel):
    pass


class NoteParams(BaseModel):
    pass


class OpenParams(BaseModel):
    pass


class AddParams(BaseModel):
    a: int
    b: int


class FailParams(BaseModel):
    pass


class ReportParams(BaseModel):
    pass


class _SteerOnGenerate:
    def __init__(self, inner: Model, agents: list[Agent], text: str) -> None:
        self._inner = inner
        self._agents = agents
        self._text = text
        self._armed = True

    async def __aenter__(self) -> Self:
        await self._inner.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._inner.__aexit__(exc_type, exc_value, traceback)

    async def add_user_message(self, text: str) -> UserMessage:
        return await self._inner.add_user_message(text)

    async def add_tool_result_message(self, tool_call_id: str, text: str) -> ToolResultMessage:
        return await self._inner.add_tool_result_message(tool_call_id, text)

    async def generate(self) -> AssistantMessage:
        if self._armed:
            self._armed = False
            self._agents[0].steer(self._text)
        return await self._inner.generate()


class _GatedModel:
    def __init__(self, inner: Model) -> None:
        self._inner = inner
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    async def __aenter__(self) -> Self:
        await self._inner.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._inner.__aexit__(exc_type, exc_value, traceback)

    async def add_user_message(self, text: str) -> UserMessage:
        return await self._inner.add_user_message(text)

    async def add_tool_result_message(self, tool_call_id: str, text: str) -> ToolResultMessage:
        return await self._inner.add_tool_result_message(tool_call_id, text)

    async def generate(self) -> AssistantMessage:
        self.reached.set()
        await self.release.wait()
        return await self._inner.generate()


class BoomModel:
    def __init__(self, inner: Model, failing: str) -> None:
        self._inner = inner
        self._failing = failing
        self.exited = False

    async def __aenter__(self) -> Self:
        await self._inner.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exited = True
        await self._inner.__aexit__(exc_type, exc_value, traceback)

    async def add_user_message(self, text: str) -> UserMessage:
        if self._failing == "add_user_message":
            raise RuntimeError("provider 500")
        return await self._inner.add_user_message(text)

    async def add_tool_result_message(self, tool_call_id: str, text: str) -> ToolResultMessage:
        if self._failing == "add_tool_result_message":
            raise RuntimeError("provider 500")
        return await self._inner.add_tool_result_message(tool_call_id, text)

    async def generate(self) -> AssistantMessage:
        if self._failing == "generate":
            raise RuntimeError("provider 500")
        return await self._inner.generate()


async def test_duplicate_tool_names_raise_at_construction() -> None:
    model = FakeModel([])

    async def ping(_: PingParams) -> AgentToolResult:
        return AgentToolResult(text="pong")

    tool_a = create_agent_tool("dup", "first duplicate", PingParams, ping)
    tool_b = create_agent_tool("dup", "second duplicate", PingParams, ping)

    with pytest.raises(ValueError):
        Agent(model, tools=[tool_a, tool_b])

    assert model.history == ()


async def test_prompt_streams_start_events_then_end() -> None:
    model = FakeModel([response("a1", text="hello there")])
    agent = Agent(model, tools=[])

    async with model:
        events = await collect(agent.prompt("hello"))

    assert [type(event) for event in events] == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentEnd,
    ]
    assert [event for event in events if isinstance(event, AgentStart)] == [AgentStart()]
    user = events[2]
    assert isinstance(user, UserMessage)
    assert user.content[0].text == "hello"
    assistant = events[3]
    assert isinstance(assistant, AssistantMessage)
    assert assistant.id == "a1"
    end = events[-1]
    assert isinstance(end, AgentEnd)
    assert end.termination == "final_response"
    assert len(end.turns) == 1
    message_events = [
        event
        for event in events
        if isinstance(event, (UserMessage, AssistantMessage, ToolResultMessage))
    ]
    assert end.messages == message_events
    assert end.turns[0].messages == message_events
    turn = end.turns[0]
    assert turn.generations == 1
    assert [m.content[0].text for m in turn.user_messages] == ["hello"]
    assert turn.tool_result_messages == []
    assert turn.assistant_message.content[0].text == "hello there"
    assert [type(m) for m in model.history] == [UserMessage, AssistantMessage]
    assert agent.is_idle()


async def test_multi_turn_run_aggregates_turns_and_messages() -> None:
    model = FakeModel([response("a1", text="first answer"), response("a2", text="second answer")])
    agent = Agent(model, tools=[])

    async with model:
        stream = agent.prompt("first")
        agent.follow_up("second")

        events = await collect(stream)

    assert [type(event) for event in events] == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentEnd,
    ]
    turns = [event for event in events if isinstance(event, AgentTurnEnd)]
    assert len(turns) == 2
    first_user = events[2]
    assert isinstance(first_user, UserMessage)
    assert first_user.content[0].text == "first"
    second_user = events[6]
    assert isinstance(second_user, UserMessage)
    assert second_user.content[0].text == "second"
    end = events[-1]
    assert isinstance(end, AgentEnd)
    assert end.turns == turns
    assert end.messages == turns[0].messages + turns[1].messages
    assert end.termination == "final_response"
    assert [m.content[0].text for m in turns[0].user_messages] == ["first"]
    assert [m.content[0].text for m in turns[1].user_messages] == ["second"]
    assert [turn.assistant_message.id for turn in turns] == ["a1", "a2"]
    assert all(turn.generations == 1 for turn in turns)
    assert agent.is_idle()


async def test_idle_lifecycle_across_run() -> None:
    model = FakeModel([response("a1", text="hello there")])
    agent = Agent(model, tools=[])

    assert agent.is_idle()

    async with model:
        stream = agent.prompt("hello")
        assert not agent.is_idle()

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(agent.wait_for_idle(), timeout=0.05)

        await collect(stream)

        assert agent.is_idle()
        await asyncio.wait_for(agent.wait_for_idle(), timeout=1)

    assert agent.is_idle()


async def test_prompt_while_active_raises() -> None:
    model = FakeModel([response("a1", text="one"), response("a2", text="two")])
    agent = Agent(model, tools=[])

    async with model:
        stream = agent.prompt("first")
        assert not agent.is_idle()

        with pytest.raises(RuntimeError):
            agent.prompt("second")

        events = await collect(stream)
        assert [type(event) for event in events] == [
            AgentStart,
            AgentTurnStart,
            UserMessage,
            AssistantMessage,
            AgentTurnEnd,
            AgentEnd,
        ]

        recovery = await collect(agent.prompt("second"))
        assert [type(event) for event in recovery] == [
            AgentStart,
            AgentTurnStart,
            UserMessage,
            AssistantMessage,
            AgentTurnEnd,
            AgentEnd,
        ]

    assert agent.is_idle()


async def test_steer_and_follow_up_raise_while_idle() -> None:
    model = FakeModel([response("a1", text="hello there")])
    agent = Agent(model, tools=[])

    with pytest.raises(RuntimeError):
        agent.steer("x")
    with pytest.raises(RuntimeError):
        agent.follow_up("y")

    async with model:
        await collect(agent.prompt("hello"))

    assert agent.is_idle()

    with pytest.raises(RuntimeError):
        agent.steer("x")
    with pytest.raises(RuntimeError):
        agent.follow_up("y")


async def test_steer_routes_to_live_run_mid_generation() -> None:
    agents: list[Agent] = []

    async def note(_: NoteParams) -> AgentToolResult:
        agents[0].steer("first correction")
        agents[0].steer("second correction")
        return AgentToolResult(text="noted")

    tool = create_agent_tool("note", "notes things", NoteParams, note)
    model = FakeModel(
        [
            response(
                "a1",
                text="working",
                tool_calls=[ToolCall(id="c1", tool_name="note", parameters={})],
            ),
            response("a2", text="done"),
        ]
    )
    agent = Agent(model, tools=[tool])
    agents.append(agent)

    async with model:
        events = await collect(agent.prompt("hello"))

    assert [type(event) for event in events] == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        UserMessage,
        UserMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentEnd,
    ]
    steered = events[5]
    assert isinstance(steered, UserMessage)
    assert steered.content[0].text == "first correction"
    second = events[6]
    assert isinstance(second, UserMessage)
    assert second.content[0].text == "second correction"
    assert [type(message) for message in model.history] == [
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        UserMessage,
        UserMessage,
        AssistantMessage,
    ]
    end = events[-1]
    assert isinstance(end, AgentEnd)
    assert end.termination == "final_response"
    turn = end.turns[0]
    assert [m.content[0].text for m in turn.user_messages] == [
        "hello",
        "first correction",
        "second correction",
    ]
    feedback = model.history[2]
    assert isinstance(feedback, ToolResultMessage)
    assert feedback.tool_call_id == "c1"
    assert turn.tool_result_messages == [feedback]
    assert turn.tool_result_messages[0].content[0].text == "noted"
    assert agent.is_idle()


async def test_follow_up_from_within_tool_schedules_next_turn() -> None:
    agents: list[Agent] = []

    async def schedule(_: ScheduleParams) -> AgentToolResult:
        agents[0].follow_up("queued question")
        return AgentToolResult(text="scheduled")

    tool = create_agent_tool("schedule", "schedules a follow-up", ScheduleParams, schedule)
    model = FakeModel(
        [
            response(
                "a1",
                text="working",
                tool_calls=[ToolCall(id="c1", tool_name="schedule", parameters={})],
            ),
            response("a2", text="first done"),
            response("a3", text="second done"),
        ]
    )
    agent = Agent(model, tools=[tool])
    agents.append(agent)

    async with model:
        events = await collect(agent.prompt("hello"))

    assert [type(event) for event in events] == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentEnd,
    ]
    turns = [event for event in events if isinstance(event, AgentTurnEnd)]
    assert len(turns) == 2
    assert [m.content[0].text for m in turns[0].user_messages] == ["hello"]
    assert [m.content[0].text for m in turns[1].user_messages] == ["queued question"]
    assert turns[0].generations == 2
    assert turns[1].generations == 1
    message_events = [
        event
        for event in events
        if isinstance(event, (UserMessage, AssistantMessage, ToolResultMessage))
    ]
    assert isinstance(message_events[2], ToolResultMessage)
    assert turns[0].tool_result_messages == [message_events[2]]
    assert message_events == list(model.history)
    assert [type(message) for message in model.history] == [
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        AssistantMessage,
        UserMessage,
        AssistantMessage,
    ]
    end = events[-1]
    assert isinstance(end, AgentEnd)
    assert end.turns == turns
    assert end.messages == turns[0].messages + turns[1].messages
    assert end.termination == "final_response"
    assert agent.is_idle()


async def test_multiple_tool_calls_execute_in_order_and_answer_each() -> None:
    received: list[dict[str, Any]] = []

    async def add(params: AddParams) -> AgentToolResult:
        received.append(params.model_dump())
        return AgentToolResult(text=str(params.a + params.b))

    tool = create_agent_tool("add", "adds two integers", AddParams, add)
    model = FakeModel(
        [
            response(
                "a1",
                text="running two",
                tool_calls=[
                    ToolCall(id="c1", tool_name="add", parameters={"a": 2, "b": 3}),
                    ToolCall(id="c2", tool_name="add", parameters={"a": 10, "b": 20}),
                ],
            ),
            response("a2", text="done"),
        ]
    )
    agent = Agent(model, tools=[tool])

    async with model:
        events = await collect(agent.prompt("add twice"))

    assert [type(event) for event in events] == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        ToolResultMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentEnd,
    ]
    assert received == [{"a": 2, "b": 3}, {"a": 10, "b": 20}]
    turn = events[-2]
    assert isinstance(turn, AgentTurnEnd)
    assert [m.tool_call_id for m in turn.tool_result_messages] == ["c1", "c2"]
    assert [m.content[0].text for m in turn.tool_result_messages] == ["5", "30"]
    assert [type(m) for m in model.history] == [
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        ToolResultMessage,
        AssistantMessage,
    ]
    end = events[-1]
    assert isinstance(end, AgentEnd)
    assert end.termination == "final_response"
    assert agent.is_idle()


async def test_unknown_tool_synthesizes_error_result() -> None:
    model = FakeModel(
        [
            response(
                "a1",
                text="trying",
                tool_calls=[ToolCall(id="c1", tool_name="nonexistent", parameters={})],
            ),
            response("a2", text="gave up gracefully"),
        ]
    )
    agent = Agent(model, tools=[])

    async with model:
        events = await collect(agent.prompt("use the mystery tool"))

    assert [type(event) for event in events] == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentEnd,
    ]
    feedback = model.history[2]
    assert isinstance(feedback, ToolResultMessage)
    assert feedback.tool_call_id == "c1"
    turn = events[-2]
    assert isinstance(turn, AgentTurnEnd)
    assert turn.tool_result_messages == [feedback]
    assert turn.assistant_message.id == "a2"
    end = events[-1]
    assert isinstance(end, AgentEnd)
    assert end.termination == "final_response"
    assert agent.is_idle()


async def test_tool_exception_contained_as_error_result() -> None:
    async def explode(_: FailParams) -> AgentToolResult:
        raise RuntimeError("disk on fire")

    tool = create_agent_tool("explode", "always raises", FailParams, explode)
    model = FakeModel(
        [
            response(
                "a1",
                text="trying",
                tool_calls=[ToolCall(id="c1", tool_name="explode", parameters={})],
            ),
            response("a2", text="handled it"),
        ]
    )
    agent = Agent(model, tools=[tool])

    async with model:
        events = await collect(agent.prompt("trigger the failure"))

    assert [type(event) for event in events] == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentEnd,
    ]
    feedback = model.history[2]
    assert isinstance(feedback, ToolResultMessage)
    assert feedback.tool_call_id == "c1"
    turn = events[-2]
    assert isinstance(turn, AgentTurnEnd)
    assert turn.tool_result_messages == [feedback]
    assert turn.assistant_message.id == "a2"
    end = events[-1]
    assert isinstance(end, AgentEnd)
    assert end.termination == "final_response"
    assert agent.is_idle()


async def test_tool_terminate_end_event_reflects_it() -> None:
    executed: list[dict[str, Any]] = []

    async def maybe_stop(params: StopParams) -> AgentToolResult:
        executed.append(params.model_dump())
        return AgentToolResult(
            text="stopping" if params.stop else "continuing", terminate=params.stop
        )

    tool = create_agent_tool("maybe_stop", "stops when asked", StopParams, maybe_stop)
    model = FakeModel(
        [
            response(
                "a1",
                text="running two",
                tool_calls=[
                    ToolCall(id="c1", tool_name="maybe_stop", parameters={"stop": True}),
                    ToolCall(id="c2", tool_name="maybe_stop", parameters={"stop": False}),
                ],
            ),
        ]
    )
    agent = Agent(model, tools=[tool])

    async with model:
        events = await collect(agent.prompt("try both"))

    assert [type(event) for event in events] == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        ToolResultMessage,
        AgentTurnEnd,
        AgentEnd,
    ]
    assert executed == [{"stop": True}, {"stop": False}]
    assert [m.tool_call_id for m in model.history if isinstance(m, ToolResultMessage)] == [
        "c1",
        "c2",
    ]
    end = events[-1]
    assert isinstance(end, AgentEnd)
    assert end.termination == "tool_terminated"
    assert len(end.turns) == 1
    turn = end.turns[0]
    assert turn.termination == "tool_terminated"
    assert turn.generations == 1
    assert [m.tool_call_id for m in turn.tool_result_messages] == ["c1", "c2"]
    assert [m.content[0].text for m in turn.user_messages] == ["try both"]
    assert end.messages == turn.messages
    assert agent.is_idle()


async def test_exhausted_propagates_and_agent_recovers() -> None:
    async def spin(_: SpinParams) -> AgentToolResult:
        return AgentToolResult(text="spun")

    tool = create_agent_tool("spin", "spins without finishing", SpinParams, spin)
    model = FakeModel(
        [
            response("a1", text="first answer"),
            response(
                "a2", text="more", tool_calls=[ToolCall(id="c2", tool_name="spin", parameters={})]
            ),
            response(
                "a3", text="more", tool_calls=[ToolCall(id="c3", tool_name="spin", parameters={})]
            ),
            response("a4", text="done"),
        ]
    )
    options = AgentOptions(agent_loop_options=AgentLoopOptions(max_generations=3))
    agent = Agent(model, tools=[tool], options=options)

    async with model:
        stream = agent.prompt("first")
        agent.follow_up("second")
        events: list[AgentEvent] = []
        with pytest.raises(AgentLoopExhausted):
            async for event in stream:
                events.append(event)

        assert not any(isinstance(event, AgentEnd) for event in events)
        assert [type(event) for event in events] == [
            AgentStart,
            AgentTurnStart,
            UserMessage,
            AssistantMessage,
            AgentTurnEnd,
            AgentTurnStart,
            UserMessage,
            AssistantMessage,
            ToolResultMessage,
            AssistantMessage,
            ToolResultMessage,
        ]
        completed = [event for event in events if isinstance(event, AgentTurnEnd)]
        assert [turn.assistant_message.id for turn in completed] == ["a1"]
        assert [turn.generations for turn in completed] == [1]
        assert len([m for m in model.history if isinstance(m, AssistantMessage)]) == 3
        assert [m.tool_call_id for m in model.history if isinstance(m, ToolResultMessage)] == [
            "c2",
            "c3",
        ]
        assert agent.is_idle()
        await asyncio.wait_for(agent.wait_for_idle(), timeout=1)

        recovery = await collect(agent.prompt("again"))

    assert [type(event) for event in recovery] == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentEnd,
    ]
    assert agent.is_idle()


async def test_stranded_steering_propagates_and_agent_recovers() -> None:
    model = FakeModel([response("a1", text="done"), response("a2", text="done again")])
    agents: list[Agent] = []
    wrapper = _SteerOnGenerate(model, agents, "too late")
    agent = Agent(wrapper, tools=[])
    agents.append(agent)

    async with model:
        events: list[AgentEvent] = []
        with pytest.raises(AgentLoopStranded):
            async for event in agent.prompt("hello"):
                events.append(event)

        assert not any(isinstance(event, AgentEnd) for event in events)
        assert [type(event) for event in events] == [
            AgentStart,
            AgentTurnStart,
            UserMessage,
            AssistantMessage,
            AgentTurnEnd,
        ]
        assert agent.is_idle()
        await asyncio.wait_for(agent.wait_for_idle(), timeout=1)

        recovery = await collect(agent.prompt("again"))

    assert [type(event) for event in recovery] == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentEnd,
    ]
    assert agent.is_idle()


async def test_early_stream_closure_returns_agent_to_idle() -> None:
    model = FakeModel([response("a1", text="hello there")])
    wrapper = _GatedModel(model)
    agent = Agent(wrapper, tools=[])

    async with model:
        stream = agent.prompt("hello")
        assert not agent.is_idle()

        consumer = asyncio.create_task(collect(stream))
        try:
            await asyncio.wait_for(wrapper.reached.wait(), timeout=1)
            consumer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await consumer
        finally:
            consumer.cancel()

        assert agent.is_idle()
        await asyncio.wait_for(agent.wait_for_idle(), timeout=1)
        assert [type(message) for message in model.history] == [UserMessage]

        wrapper.release.set()
        recovery = await collect(agent.prompt("again"))

    assert [type(event) for event in recovery] == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentEnd,
    ]
    assert agent.is_idle()


async def test_prompt_is_lazy_until_iterated() -> None:
    model = FakeModel([response("a1", text="hello there")])
    agent = Agent(model, tools=[])

    async with model:
        stream = agent.prompt("hello")

        for _ in range(5):
            await asyncio.sleep(0)

        assert len(model.history) == 0

        events = await collect(stream)

    assert [type(event) for event in events] == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentEnd,
    ]
    assert [type(message) for message in model.history] == [UserMessage, AssistantMessage]
    assert agent.is_idle()


async def test_hooks_forwarded_to_run() -> None:
    executed: list[str] = []

    async def guarded(_: GuardedParams) -> AgentToolResult:
        executed.append("guarded")
        return AgentToolResult(text="should not happen")

    async def open_tool(_: OpenParams) -> AgentToolResult:
        executed.append("open")
        return AgentToolResult(text="ok")

    tools = [
        create_agent_tool("guarded", "a guarded tool", GuardedParams, guarded),
        create_agent_tool("open", "an open tool", OpenParams, open_tool),
    ]

    async def before_tool_call(call: ToolCall) -> ToolCallDecision:
        if call.tool_name == "guarded":
            return ToolCallDecision(action="deny", reason="denied by policy")
        return ToolCallDecision(action="run")

    reviewed_inputs: list[str] = []

    async def review(_: ToolCall, result: AgentToolResult) -> AgentToolResult:
        reviewed_inputs.append(result.text)
        return AgentToolResult(
            text=f"{result.text} [reviewed]",
            is_error=result.is_error,
            terminate=result.terminate,
        )

    hooks = AgentHooks(before_tool_call=before_tool_call, tool_result=review)
    model = FakeModel(
        [
            response(
                "a1",
                text="working",
                tool_calls=[
                    ToolCall(id="c1", tool_name="guarded", parameters={}),
                    ToolCall(id="c2", tool_name="open", parameters={}),
                ],
            ),
            response("a2", text="done"),
        ]
    )
    agent = Agent(model, tools=tools, hooks=hooks)

    async with model:
        events = await collect(agent.prompt("hello"))

    assert executed == ["open"]
    denied = events[4]
    assert isinstance(denied, ToolResultMessage)
    assert denied.tool_call_id == "c1"
    assert denied.content[0].text == "denied by policy"
    reviewed = events[5]
    assert isinstance(reviewed, ToolResultMessage)
    assert reviewed.tool_call_id == "c2"
    assert reviewed.content[0].text == "ok [reviewed]"
    end = events[-1]
    assert isinstance(end, AgentEnd)
    assert end.termination == "final_response"
    assert len(end.turns) == 1
    assert reviewed_inputs == ["ok"]
    assert end.turns[0].tool_result_messages == [denied, reviewed]
    assert agent.is_idle()


async def test_before_tool_call_fires_for_unknown_tools() -> None:
    observed: list[str] = []

    async def observe(call: ToolCall) -> ToolCallDecision:
        observed.append(f"{call.id}:{call.tool_name}")
        return ToolCallDecision(action="run")

    model = FakeModel(
        [
            response(
                "a1",
                text="trying",
                tool_calls=[ToolCall(id="c1", tool_name="ghost", parameters={})],
            ),
            response("a2", text="understood"),
        ]
    )
    agent = Agent(model, tools=[], hooks=AgentHooks(before_tool_call=observe))

    async with model:
        events = await collect(agent.prompt("try it"))

    assert observed == ["c1:ghost"]
    feedback = model.history[2]
    assert isinstance(feedback, ToolResultMessage)
    assert feedback.tool_call_id == "c1"
    turn = events[-2]
    assert isinstance(turn, AgentTurnEnd)
    assert turn.tool_result_messages == [feedback]
    assert turn.assistant_message.id == "a2"
    end = events[-1]
    assert isinstance(end, AgentEnd)
    assert end.termination == "final_response"
    assert agent.is_idle()


async def test_tool_result_hook_can_escalate_termination() -> None:
    async def report(_: ReportParams) -> AgentToolResult:
        return AgentToolResult(text="finished normally")

    async def escalate(_: ToolCall, result: AgentToolResult) -> AgentToolResult:
        return result.model_copy(update={"terminate": True})

    tool = create_agent_tool("report", "reports", ReportParams, report)
    model = FakeModel(
        [
            response(
                "a1",
                text="reporting",
                tool_calls=[ToolCall(id="c1", tool_name="report", parameters={})],
            ),
        ]
    )
    agent = Agent(model, tools=[tool], hooks=AgentHooks(tool_result=escalate))

    async with model:
        events = await collect(agent.prompt("go"))

    assert [type(event) for event in events] == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        AgentTurnEnd,
        AgentEnd,
    ]
    assert [type(message) for message in model.history] == [
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
    ]
    feedback = model.history[2]
    assert isinstance(feedback, ToolResultMessage)
    assert feedback.tool_call_id == "c1"
    end = events[-1]
    assert isinstance(end, AgentEnd)
    assert end.termination == "tool_terminated"
    assert end.turns[0].termination == "tool_terminated"
    assert end.turns[0].tool_result_messages == [feedback]
    assert agent.is_idle()


async def test_hook_exceptions_propagate_and_settle_agent() -> None:
    async def ping(_: PingParams) -> AgentToolResult:
        return AgentToolResult(text="pong")

    tool = create_agent_tool("ping", "pings", PingParams, ping)
    script = [
        response(
            "a1", text="trying", tool_calls=[ToolCall(id="c1", tool_name="ping", parameters={})]
        ),
    ]

    async def before_boom(_: ToolCall) -> ToolCallDecision:
        raise RuntimeError("before hook exploded")

    model = FakeModel(script)
    agent = Agent(model, tools=[tool], hooks=AgentHooks(before_tool_call=before_boom))
    async with model:
        with pytest.raises(RuntimeError, match="before hook exploded"):
            async for _ in agent.prompt("go"):
                pass
        assert agent.is_idle()

    async def result_boom(_call: ToolCall, _result: AgentToolResult) -> AgentToolResult:
        raise RuntimeError("result hook exploded")

    model = FakeModel(script)
    agent = Agent(model, tools=[tool], hooks=AgentHooks(tool_result=result_boom))
    async with model:
        with pytest.raises(RuntimeError, match="result hook exploded"):
            async for _ in agent.prompt("go"):
                pass
        assert agent.is_idle()


async def test_model_exceptions_propagate_and_settle_agent() -> None:
    async def ping(_: PingParams) -> AgentToolResult:
        return AgentToolResult(text="pong")

    tool = create_agent_tool("ping", "pings", PingParams, ping)
    tool_call_script = [
        response(
            "a1", text="working", tool_calls=[ToolCall(id="c1", tool_name="ping", parameters={})]
        ),
    ]

    scenarios: list[tuple[str, FakeModel]] = [
        ("add_user_message", FakeModel([])),
        ("generate", FakeModel([])),
        ("add_tool_result_message", FakeModel(tool_call_script)),
    ]

    for failing, inner in scenarios:
        model = BoomModel(inner, failing)
        agent = Agent(model, tools=[tool])
        async with model:
            with pytest.raises(RuntimeError, match="provider 500"):
                async for _ in agent.prompt("go"):
                    pass
            assert agent.is_idle()
        assert model.exited is True


async def test_wait_for_idle_wakes_when_run_settles() -> None:
    model = FakeModel([response("a1", text="hello there")])
    wrapper = _GatedModel(model)
    agent = Agent(wrapper, tools=[])

    async with model:
        stream = agent.prompt("hello")
        consumer = asyncio.create_task(collect(stream))
        try:
            await asyncio.wait_for(wrapper.reached.wait(), timeout=1)

            waiter = asyncio.create_task(agent.wait_for_idle())
            await asyncio.sleep(0)

            wrapper.release.set()
            events = await asyncio.wait_for(consumer, timeout=1)
        finally:
            consumer.cancel()

        await asyncio.wait_for(waiter, timeout=1)
        assert agent.is_idle()

    assert [type(event) for event in events] == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentEnd,
    ]
    assert isinstance(events[-1], AgentEnd)


async def test_stream_is_single_use() -> None:
    model = FakeModel([response("a1", text="hello there"), response("a2", text="again")])
    agent = Agent(model, tools=[])

    async with model:
        stream = agent.prompt("hello")

        first = await collect(stream)
        assert [type(event) for event in first][-1] == AgentEnd

        with pytest.raises(RuntimeError):
            await collect(stream)

        assert agent.is_idle()

        recovery = await collect(agent.prompt("again"))

    assert [type(event) for event in recovery][-1] == AgentEnd
    assert agent.is_idle()

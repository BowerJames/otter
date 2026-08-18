import asyncio

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
    AgentModel,
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
    pass


class SpinParams(BaseModel):
    pass


class GuardedParams(BaseModel):
    pass


class _SteerOnGenerate:
    def __init__(self, inner: AgentModel, agents: list[Agent], text: str) -> None:
        self._inner = inner
        self._agents = agents
        self._text = text
        self._armed = True

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
    def __init__(self, inner: AgentModel) -> None:
        self._inner = inner
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    async def add_user_message(self, text: str) -> UserMessage:
        return await self._inner.add_user_message(text)

    async def add_tool_result_message(self, tool_call_id: str, text: str) -> ToolResultMessage:
        return await self._inner.add_tool_result_message(tool_call_id, text)

    async def generate(self) -> AssistantMessage:
        self.reached.set()
        await self.release.wait()
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
    model = FakeModel([response("a1", text="hi there")])
    agents: list[Agent] = []
    wrapper = _SteerOnGenerate(model, agents, "look at this first")
    agent = Agent(wrapper, tools=[])
    agents.append(agent)

    async with model:
        events = await collect(agent.prompt("hello"))

    assert [type(event) for event in events] == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        UserMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentEnd,
    ]
    opening = events[2]
    steered = events[3]
    assert isinstance(opening, UserMessage)
    assert isinstance(steered, UserMessage)
    assert opening.content[0].text == "hello"
    assert steered.content[0].text == "look at this first"
    assert [type(message) for message in model.history] == [
        UserMessage,
        UserMessage,
        AssistantMessage,
    ]
    end = events[-1]
    assert isinstance(end, AgentEnd)
    assert end.termination == "final_response"
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


async def test_tool_terminate_end_event_reflects_it() -> None:
    async def stop(_: StopParams) -> AgentToolResult:
        return AgentToolResult(text="stopped", terminate=True)

    tool = create_agent_tool("stop", "stops the run", StopParams, stop)
    model = FakeModel(
        [
            response(
                "a1",
                text="stopping",
                tool_calls=[ToolCall(id="c1", tool_name="stop", parameters={})],
            ),
            response("a2", text="unused guard"),
        ]
    )
    agent = Agent(model, tools=[tool])

    async with model:
        events = await collect(agent.prompt("hello"))

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
    end = events[-1]
    assert isinstance(end, AgentEnd)
    assert end.termination == "tool_terminated"
    assert len(end.turns) == 1
    assert end.turns[0].termination == "tool_terminated"
    assert end.messages == end.turns[0].messages
    assert agent.is_idle()


async def test_exhausted_propagates_and_agent_recovers() -> None:
    async def spin(_: SpinParams) -> AgentToolResult:
        return AgentToolResult(text="spun")

    tool = create_agent_tool("spin", "spins without finishing", SpinParams, spin)
    model = FakeModel(
        [
            response(
                "a1",
                text="working",
                tool_calls=[ToolCall(id="c1", tool_name="spin", parameters={})],
            ),
            response("a2", text="done"),
        ]
    )
    options = AgentOptions(agent_loop_options=AgentLoopOptions(max_generations=1))
    agent = Agent(model, tools=[tool], options=options)

    async with model:
        events: list[AgentEvent] = []
        with pytest.raises(AgentLoopExhausted):
            async for event in agent.prompt("hello"):
                events.append(event)

        assert not any(isinstance(event, AgentEnd) for event in events)
        assert [type(event) for event in events] == [
            AgentStart,
            AgentTurnStart,
            UserMessage,
            AssistantMessage,
            ToolResultMessage,
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
        executed.append("ran")
        return AgentToolResult(text="should not happen")

    tool = create_agent_tool("guarded", "a guarded tool", GuardedParams, guarded)

    async def before_tool_call(call: ToolCall) -> ToolCallDecision:
        if call.tool_name == "guarded":
            return ToolCallDecision(action="deny", reason="denied by policy")
        return ToolCallDecision(action="run")

    async def review(_: ToolCall, result: AgentToolResult) -> AgentToolResult:
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
                tool_calls=[ToolCall(id="c1", tool_name="guarded", parameters={})],
            ),
            response("a2", text="done"),
        ]
    )
    agent = Agent(model, tools=[tool], hooks=hooks)

    async with model:
        events = await collect(agent.prompt("hello"))

    assert executed == []
    feedback = events[4]
    assert isinstance(feedback, ToolResultMessage)
    assert feedback.content[0].text == "denied by policy [reviewed]"
    end = events[-1]
    assert isinstance(end, AgentEnd)
    assert end.termination == "final_response"
    assert len(end.turns) == 1
    assert agent.is_idle()


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

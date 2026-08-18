import pytest
from pydantic import BaseModel

from otter_ai_core.agent import AgentLoop, AgentLoopExhausted, AgentLoopOptions, AgentLoopTurn
from otter_ai_core.agent_tool import AgentToolResult, create_agent_tool
from otter_ai_core.conversation import (
    AssistantMessage,
    SessionMessage,
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


class TimeParams(BaseModel):
    pass


class NoteParams(BaseModel):
    pass


class CountParams(BaseModel):
    pass


async def test_event_stream_interleaves_session_messages_and_turn() -> None:
    async def get_time(_: TimeParams) -> AgentToolResult:
        return AgentToolResult(text="12:00")

    tool = create_agent_tool("get_time", "returns the time", TimeParams, get_time)
    model = FakeModel(
        [
            response(
                "a1",
                text="checking",
                tool_calls=[ToolCall(id="c1", tool_name="get_time", parameters={})],
            ),
            response("a2", text="it is 12:00"),
        ]
    )
    async with model:
        loop = AgentLoop(model, tools=[tool])
        loop.follow_up("what time is it?")

        events: list[SessionMessage | AgentLoopTurn] = [event async for event in loop]

    assert [type(event) for event in events] == [
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        AssistantMessage,
        AgentLoopTurn,
    ]
    message_events = [event for event in events if not isinstance(event, AgentLoopTurn)]
    assert message_events == list(model.history)
    turn = events[-1]
    assert isinstance(turn, AgentLoopTurn)
    assert turn.termination == "final_response"
    assert turn.messages == message_events
    assert turn.tool_executions[0].tool_name == "get_time"


async def test_steered_user_message_appears_between_generations() -> None:
    loop_ref: list[AgentLoop] = []

    async def note(_: NoteParams) -> AgentToolResult:
        loop_ref[0].steer("say it in UTC")
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
    async with model:
        loop = AgentLoop(model, tools=[tool])
        loop_ref.append(loop)
        loop.follow_up("go")

        events = [event async for event in loop]

    assert [type(event) for event in events] == [
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
        UserMessage,
        AssistantMessage,
        AgentLoopTurn,
    ]
    steered = events[3]
    assert isinstance(steered, UserMessage)
    assert steered.content[0].text == "say it in UTC"


async def test_each_turn_closes_with_a_turn_event() -> None:
    model = FakeModel(
        [
            response("a1", text="one"),
            response("a2", text="two"),
            response("a3", text="three"),
        ]
    )
    async with model:
        loop = AgentLoop(model)
        loop.follow_up("first")
        loop.follow_up("second")
        loop.follow_up("third")

        events = [event async for event in loop]

    assert [type(event) for event in events] == [
        UserMessage,
        AssistantMessage,
        AgentLoopTurn,
        UserMessage,
        AssistantMessage,
        AgentLoopTurn,
        UserMessage,
        AssistantMessage,
        AgentLoopTurn,
    ]
    turns = [event for event in events if isinstance(event, AgentLoopTurn)]
    assert [turn.assistant_message.id for turn in turns] == ["a1", "a2", "a3"]


async def test_event_stream_empty_without_follow_ups() -> None:
    model = FakeModel([])
    async with model:
        loop = AgentLoop(model)

        events = [event async for event in loop]

    assert events == []


async def test_message_events_stream_from_partial_turn_before_exhaustion() -> None:
    async def count(_: CountParams) -> AgentToolResult:
        return AgentToolResult(text="counted")

    tool = create_agent_tool("count", "counts", CountParams, count)
    model = FakeModel(
        [
            response("a1", text="first answer"),
            response(
                "a2", text="more", tool_calls=[ToolCall(id="c2", tool_name="count", parameters={})]
            ),
        ]
    )
    async with model:
        loop = AgentLoop(model, tools=[tool], options=AgentLoopOptions(max_generations=2))
        loop.follow_up("first")
        loop.follow_up("second")

        events: list[SessionMessage | AgentLoopTurn] = []
        with pytest.raises(AgentLoopExhausted):
            async for event in loop:
                events.append(event)

    assert [type(event) for event in events] == [
        UserMessage,
        AssistantMessage,
        AgentLoopTurn,
        UserMessage,
        AssistantMessage,
        ToolResultMessage,
    ]

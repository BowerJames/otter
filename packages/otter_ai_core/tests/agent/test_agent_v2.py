import asyncio
from collections.abc import AsyncIterable
from unittest.mock import AsyncMock, MagicMock, NonCallableMagicMock

import pytest
from pydantic import BaseModel

from otter_ai_core.agent_tool_factory import create_agent_tool
from otter_ai_core.agent_v2 import (
    Agent,
    AgentEvents,
    AgentIterationEndEvent,
    AgentIterationStartEvent,
    AgentSessionMessageEvent,
    AgentTurnEndEvent,
    AgentTurnStartEvent,
)
from otter_ai_core.components import Gate
from otter_ai_core.types import (
    AgentToolResult,
    AssistantMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

from ..support import script


async def collect(
    stream: AsyncIterable[AgentEvents], into: list[AgentEvents] | None = None
) -> list[AgentEvents]:
    events = [] if into is None else into
    async for event in stream:
        events.append(event)
    return events


@pytest.mark.timeout(1)
async def test_duplicate_tool_names_raise_at_construction(mock_model: MagicMock) -> None:
    class NoParams(BaseModel):
        pass

    tool_a = create_agent_tool("dup", "first duplicate", NoParams, AsyncMock())
    tool_b = create_agent_tool("dup", "second duplicate", NoParams, AsyncMock())
    with pytest.raises(ValueError):
        Agent(mock_model, tools=[tool_a, tool_b])


@pytest.mark.timeout(1)
async def test_single_turn_agent_loop_events_order(
    mock_model: MagicMock,
) -> None:
    script(mock_model.add_user_message, lambda text: NonCallableMagicMock(spec=UserMessage))

    final = NonCallableMagicMock(spec=AssistantMessage)
    final.stop_reason = "final_response"
    script(mock_model.generate, [final])

    async with mock_model:
        agent = Agent(mock_model, tools=[])
        task = asyncio.create_task(collect(agent.stream()))
        agent.prompt("hello")
        await agent.wait_for_idle()
        agent.cancel_stream()
        events = await task

    assert [type(event) for event in events] == [
        AgentTurnStartEvent,
        AgentIterationStartEvent,
        AgentSessionMessageEvent,
        AgentSessionMessageEvent,
        AgentIterationEndEvent,
        AgentTurnEndEvent,
    ]
    user_message = mock_model.add_user_message.outcomes[0]

    user_added = events[2]
    assistant_added = events[3]
    assert isinstance(user_added, AgentSessionMessageEvent)
    assert isinstance(assistant_added, AgentSessionMessageEvent)
    assert user_added.message is user_message
    assert assistant_added.message is final

    iteration_end = events[4]
    assert isinstance(iteration_end, AgentIterationEndEvent)
    assert iteration_end.termination == "final_response"
    assert iteration_end.user_messages == [user_message]
    assert iteration_end.assistant_message is final
    assert iteration_end.tool_result_messages is None

    turn_end = events[5]
    assert isinstance(turn_end, AgentTurnEndEvent)
    assert turn_end.termination == "final_response"
    assert turn_end.iterations[0].user_messages == [user_message]
    assert turn_end.iterations[0].assistant_message is final
    assert turn_end.iterations[0].tool_result_messages is None


@pytest.mark.timeout(1)
async def test_single_turn_tool_round_trip_events_order(
    mock_model: MagicMock,
) -> None:
    class NoParams(BaseModel):
        pass

    script(mock_model.add_user_message, lambda text: NonCallableMagicMock(spec=UserMessage))

    call_id = object()
    tool_call = NonCallableMagicMock(spec=ToolCall)
    tool_call.id = call_id
    tool_call.tool_name = "stop"
    tool_call.parameters = {}

    tool_call_message = NonCallableMagicMock(spec=AssistantMessage)
    tool_call_message.stop_reason = "tool_call"
    tool_call_message.tool_calls = [tool_call]

    final = NonCallableMagicMock(spec=AssistantMessage)
    final.stop_reason = "final_response"
    script(mock_model.generate, [tool_call_message, final])

    script(
        mock_model.add_tool_result_message,
        lambda tool_call_id, text: NonCallableMagicMock(spec=ToolResultMessage),
    )

    execute = AsyncMock(return_value=AgentToolResult(text="stopped"))
    stop_tool = create_agent_tool("stop", "requests the final response", NoParams, execute)

    async with mock_model:
        agent = Agent(mock_model, tools=[stop_tool])
        task = asyncio.create_task(collect(agent.stream()))
        agent.prompt("hello")
        await agent.wait_for_idle()
        agent.cancel_stream()
        events = await task

    assert [type(event) for event in events] == [
        AgentTurnStartEvent,
        AgentIterationStartEvent,
        AgentSessionMessageEvent,
        AgentSessionMessageEvent,
        AgentSessionMessageEvent,
        AgentIterationEndEvent,
        AgentIterationStartEvent,
        AgentSessionMessageEvent,
        AgentIterationEndEvent,
        AgentTurnEndEvent,
    ]

    user_message = mock_model.add_user_message.outcomes[0]
    tool_result = mock_model.add_tool_result_message.outcomes[0]

    assert execute.await_args_list[0].args[0] == NoParams()
    assert mock_model.add_tool_result_message.await_args_list[0].args[0] is call_id
    assert mock_model.add_tool_result_message.await_args_list[0].args[1] == "stopped"
    assert len(mock_model.add_user_message.outcomes) == 1

    user_added, assistant1_added, tool_result_added, assistant2_added = (
        events[2],
        events[3],
        events[4],
        events[7],
    )
    assert isinstance(user_added, AgentSessionMessageEvent)
    assert isinstance(assistant1_added, AgentSessionMessageEvent)
    assert isinstance(tool_result_added, AgentSessionMessageEvent)
    assert isinstance(assistant2_added, AgentSessionMessageEvent)
    assert user_added.message is user_message
    assert assistant1_added.message is tool_call_message
    assert tool_result_added.message is tool_result
    assert assistant2_added.message is final

    iteration1_end = events[5]
    assert isinstance(iteration1_end, AgentIterationEndEvent)
    assert iteration1_end.termination == "tool_response"
    assert iteration1_end.user_messages == [user_message]
    assert iteration1_end.assistant_message is tool_call_message
    assert iteration1_end.tool_result_messages == [tool_result]

    iteration2_end = events[8]
    assert isinstance(iteration2_end, AgentIterationEndEvent)
    assert iteration2_end.termination == "final_response"
    assert iteration2_end.user_messages == []
    assert iteration2_end.assistant_message is final
    assert iteration2_end.tool_result_messages is None

    turn_end = events[9]
    assert isinstance(turn_end, AgentTurnEndEvent)
    assert turn_end.termination == "final_response"
    assert turn_end.iterations[0].user_messages == [user_message]
    assert turn_end.iterations[0].assistant_message is tool_call_message
    assert turn_end.iterations[0].tool_result_messages == [tool_result]
    assert turn_end.iterations[1].user_messages == []
    assert turn_end.iterations[1].assistant_message is final
    assert turn_end.iterations[1].tool_result_messages is None


@pytest.mark.timeout(1)
async def test_agent_awaits_each_model_call_before_proceeding(
    mock_model: MagicMock,
) -> None:
    class NoParams(BaseModel):
        pass

    gate = Gate()

    user_message = NonCallableMagicMock(spec=UserMessage)

    call_id = object()
    tool_call = NonCallableMagicMock(spec=ToolCall)
    tool_call.id = call_id
    tool_call.tool_name = "stop"
    tool_call.parameters = {}

    tool_call_message = NonCallableMagicMock(spec=AssistantMessage)
    tool_call_message.stop_reason = "tool_call"
    tool_call_message.tool_calls = [tool_call]

    final = NonCallableMagicMock(spec=AssistantMessage)
    final.stop_reason = "final_response"

    responses = iter([tool_call_message, final])

    async def gated_add_user_message(text: str) -> NonCallableMagicMock:
        await gate.wait_for_open()
        return user_message

    async def gated_generate() -> NonCallableMagicMock:
        await gate.wait_for_open()
        return next(responses)

    tool_result = NonCallableMagicMock(spec=ToolResultMessage)

    async def gated_add_tool_result_message(tool_call_id: str, text: str) -> NonCallableMagicMock:
        await gate.wait_for_open()
        return tool_result

    script(mock_model.add_user_message, gated_add_user_message)
    script(mock_model.generate, gated_generate)
    script(mock_model.add_tool_result_message, gated_add_tool_result_message)

    execute = AsyncMock(return_value=AgentToolResult(text="stopped"))
    stop_tool = create_agent_tool("stop", "requests the final response", NoParams, execute)

    async with mock_model:
        agent = Agent(mock_model, tools=[stop_tool])
        events: list[AgentEvents] = []
        task = asyncio.create_task(collect(agent.stream(), events))
        agent.prompt("hello")

        # add_user_message in flight: the loop has touched nothing else
        await gate.wait_for_arrival()
        await asyncio.sleep(0)
        assert mock_model.add_user_message.await_count == 1
        assert mock_model.add_user_message.outcomes == []
        assert mock_model.generate.await_count == 0
        assert mock_model.add_tool_result_message.await_count == 0
        assert execute.await_count == 0
        assert [type(event) for event in events] == [
            AgentTurnStartEvent,
            AgentIterationStartEvent,
        ]
        assert not agent.is_idle()
        gate.open()

        # first generate in flight: the user message resolved and was emitted
        await gate.wait_for_arrival()
        await asyncio.sleep(0)
        assert mock_model.add_user_message.outcomes == [user_message]
        assert mock_model.generate.await_count == 1
        assert mock_model.generate.outcomes == []
        assert mock_model.add_tool_result_message.await_count == 0
        assert [type(event) for event in events] == [
            AgentTurnStartEvent,
            AgentIterationStartEvent,
            AgentSessionMessageEvent,
        ]
        gate.open()

        # add_tool_result_message in flight: the tool ran, nothing further
        await gate.wait_for_arrival()
        await asyncio.sleep(0)
        assert mock_model.generate.outcomes == [tool_call_message]
        assert execute.await_args_list[0].args[0] == NoParams()
        assert mock_model.add_tool_result_message.await_count == 1
        assert mock_model.add_tool_result_message.outcomes == []
        assert mock_model.add_tool_result_message.await_args_list[0].args[0] is call_id
        assert [type(event) for event in events] == [
            AgentTurnStartEvent,
            AgentIterationStartEvent,
            AgentSessionMessageEvent,
            AgentSessionMessageEvent,
        ]
        gate.open()

        # second generate in flight: the tool result resolved, iteration 1 closed
        await gate.wait_for_arrival()
        await asyncio.sleep(0)
        assert mock_model.add_tool_result_message.outcomes == [tool_result]
        assert mock_model.generate.await_count == 2
        assert mock_model.generate.outcomes == [tool_call_message]
        assert [type(event) for event in events] == [
            AgentTurnStartEvent,
            AgentIterationStartEvent,
            AgentSessionMessageEvent,
            AgentSessionMessageEvent,
            AgentSessionMessageEvent,
            AgentIterationEndEvent,
            AgentIterationStartEvent,
        ]
        gate.open()

        await agent.wait_for_idle()
        agent.cancel_stream()
        await task

    assert [type(event) for event in events] == [
        AgentTurnStartEvent,
        AgentIterationStartEvent,
        AgentSessionMessageEvent,
        AgentSessionMessageEvent,
        AgentSessionMessageEvent,
        AgentIterationEndEvent,
        AgentIterationStartEvent,
        AgentSessionMessageEvent,
        AgentIterationEndEvent,
        AgentTurnEndEvent,
    ]
    turn_end = events[-1]
    assert isinstance(turn_end, AgentTurnEndEvent)
    assert turn_end.termination == "final_response"
    assert len(turn_end.iterations) == 2

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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
from otter_ai_core.components.gate import Gate
from otter_ai_core.types.conversation import AssistantMessage

from ..support import script
from .helpers import (
    mock_agent_tool_result,
    mock_assistant_message,
    mock_string,
    mock_tool_call,
    mock_tool_result_message,
    mock_user_message,
)


async def collect(
    stream: AsyncIterable[AgentEvents], into: list[AgentEvents] | None = None
) -> list[AgentEvents]:
    events = [] if into is None else into
    async for event in stream:
        events.append(event)
    return events


@pytest.mark.timeout(1)
async def test_duplicate_tool_names(mock_model: MagicMock) -> None:
    class NoParams(BaseModel):
        pass

    tool_a = create_agent_tool("dup", "first duplicate", NoParams, AsyncMock())
    tool_b = create_agent_tool("dup", "second duplicate", NoParams, AsyncMock())
    with pytest.raises(ValueError):
        Agent(mock_model, tools=[tool_a, tool_b])


@pytest.mark.timeout(1)
async def test_single_iteration_loop(
    mock_model: MagicMock,
) -> None:
    script(mock_model.add_user_message, lambda text: mock_user_message())

    script(mock_model.generate, [mock_assistant_message([])])

    async with mock_model:
        agent = Agent(mock_model, tools=[])
        task = asyncio.create_task(collect(agent.stream()))
        agent.prompt(mock_string())
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
    user_message_output = mock_model.add_user_message.outcomes[0]
    assistant_message_output = mock_model.generate.outcomes[0]

    user_added = events[2]
    assistant_added = events[3]
    assert isinstance(user_added, AgentSessionMessageEvent)
    assert isinstance(assistant_added, AgentSessionMessageEvent)
    assert user_added.message is user_message_output
    assert assistant_added.message is assistant_message_output

    iteration_end = events[4]
    assert isinstance(iteration_end, AgentIterationEndEvent)
    assert iteration_end.termination == "final_response"
    assert iteration_end.user_messages == [user_message_output]
    assert iteration_end.assistant_message is assistant_message_output
    assert iteration_end.tool_result_messages is None

    turn_end = events[5]
    assert isinstance(turn_end, AgentTurnEndEvent)
    assert turn_end.termination == "final_response"
    assert turn_end.iterations[0].user_messages == [user_message_output]
    assert turn_end.iterations[0].assistant_message is assistant_message_output
    assert turn_end.iterations[0].tool_result_messages is None


@pytest.mark.timeout(1)
async def test_single_turn_with_tool_call(
    mock_model: MagicMock,
) -> None:
    class NoParams(BaseModel):
        pass

    script(mock_model.add_user_message, [mock_user_message()])

    call_id = mock_string()
    tool_name = "stop"
    tool_parameters: dict[str, Any] = {}
    tool_call = mock_tool_call(call_id, tool_name, tool_parameters)

    script(
        mock_model.generate,
        [mock_assistant_message(tool_calls=[tool_call]), mock_assistant_message()],
    )

    script(
        mock_model.add_tool_result_message,
        lambda tool_call_id, text: mock_tool_result_message(),
    )

    tool_result = mock_agent_tool_result()
    execute = AsyncMock(return_value=tool_result)
    stop_tool = create_agent_tool("stop", "requests the final response", NoParams, execute)

    async with mock_model:
        agent = Agent(mock_model, tools=[stop_tool])
        task = asyncio.create_task(collect(agent.stream()))
        agent.prompt(mock_string())
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
    tool_result_message = mock_model.add_tool_result_message.outcomes[0]
    assistant1 = mock_model.generate.outcomes[0]
    assistant2 = mock_model.generate.outcomes[1]

    assert execute.await_args_list[0].args[0] == NoParams()
    assert mock_model.add_tool_result_message.await_args_list[0].args[0] is call_id
    assert mock_model.add_tool_result_message.await_args_list[0].args[1] is tool_result.text
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
    assert assistant1_added.message is assistant1
    assert tool_result_added.message is tool_result_message
    assert assistant2_added.message is assistant2

    iteration1_end = events[5]
    assert isinstance(iteration1_end, AgentIterationEndEvent)
    assert iteration1_end.termination == "tool_response"
    assert iteration1_end.user_messages == [user_message]
    assert iteration1_end.assistant_message is assistant1
    assert iteration1_end.tool_result_messages == [tool_result_message]

    iteration2_end = events[8]
    assert isinstance(iteration2_end, AgentIterationEndEvent)
    assert iteration2_end.termination == "final_response"
    assert iteration2_end.user_messages == []
    assert iteration2_end.assistant_message is assistant2
    assert iteration2_end.tool_result_messages is None

    turn_end = events[9]
    assert isinstance(turn_end, AgentTurnEndEvent)
    assert turn_end.termination == "final_response"
    assert turn_end.iterations[0].user_messages == [user_message]
    assert turn_end.iterations[0].assistant_message is assistant1
    assert turn_end.iterations[0].tool_result_messages == [tool_result_message]
    assert turn_end.iterations[1].user_messages == []
    assert turn_end.iterations[1].assistant_message is assistant2
    assert turn_end.iterations[1].tool_result_messages is None


@pytest.mark.timeout(1)
async def test_steering_prompt_while_generating_final_message(
    mock_model: MagicMock,
) -> None:
    user_message1 = mock_user_message()
    user_message2 = mock_user_message()
    script(mock_model.add_user_message, [user_message1, user_message2])

    gate = Gate()
    assistant_message1 = mock_assistant_message()
    assistant_message2 = mock_assistant_message()

    async def generate() -> AsyncIterator[AssistantMessage]:
        await gate.wait_for_open()
        yield assistant_message1
        yield assistant_message2

    script(mock_model.generate, generate)

    async with mock_model:
        agent = Agent(mock_model, tools=[])
        task = asyncio.create_task(collect(agent.stream()))
        agent.prompt(mock_string())
        await gate.wait_for_arrival()
        agent.prompt(mock_string())
        gate.open()
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
        AgentTurnStartEvent,
        AgentIterationStartEvent,
        AgentSessionMessageEvent,
        AgentSessionMessageEvent,
        AgentIterationEndEvent,
        AgentTurnEndEvent,
    ]


@pytest.mark.timeout(1)
async def test_steering_prompt_while_generating_tool_call_message(
    mock_model: MagicMock,
) -> None:
    class NoParams(BaseModel):
        pass

    user_message1 = mock_user_message()
    user_message2 = mock_user_message()
    script(mock_model.add_user_message, [user_message1, user_message2])

    gate = Gate()
    call_id = mock_string()
    tool_name = "stop"
    tool_parameters: dict[str, Any] = {}
    tool_call = mock_tool_call(call_id, tool_name, tool_parameters)

    assistant_message1 = mock_assistant_message(tool_calls=[tool_call])
    assistant_message2 = mock_assistant_message()

    async def generate() -> AsyncIterator[AssistantMessage]:
        await gate.wait_for_open()
        yield assistant_message1
        yield assistant_message2

    script(mock_model.generate, generate)

    script(
        mock_model.add_tool_result_message,
        lambda tool_call_id, text: mock_tool_result_message(),
    )

    tool_result = mock_agent_tool_result()
    execute = AsyncMock(return_value=tool_result)
    stop_tool = create_agent_tool("stop", "requests the final response", NoParams, execute)

    async with mock_model:
        agent = Agent(mock_model, tools=[stop_tool])
        task = asyncio.create_task(collect(agent.stream()))
        agent.prompt(mock_string())
        await gate.wait_for_arrival()
        agent.prompt(mock_string())
        gate.open()
        await agent.wait_for_idle()
        agent.cancel_stream()
        events = await task

    tool_result_message = mock_model.add_tool_result_message.outcomes[0]

    assert [type(event) for event in events] == [
        AgentTurnStartEvent,
        AgentIterationStartEvent,
        AgentSessionMessageEvent,
        AgentSessionMessageEvent,
        AgentSessionMessageEvent,
        AgentIterationEndEvent,
        AgentIterationStartEvent,
        AgentSessionMessageEvent,
        AgentSessionMessageEvent,
        AgentIterationEndEvent,
        AgentTurnEndEvent,
    ]

    user_message1_added = events[2]
    assistant1_added = events[3]
    tool_result_added = events[4]
    user_message2_added = events[7]
    assistant2_added = events[8]
    assert isinstance(user_message1_added, AgentSessionMessageEvent)
    assert isinstance(assistant1_added, AgentSessionMessageEvent)
    assert isinstance(tool_result_added, AgentSessionMessageEvent)
    assert isinstance(user_message2_added, AgentSessionMessageEvent)
    assert isinstance(assistant2_added, AgentSessionMessageEvent)
    assert user_message1_added.message is user_message1
    assert assistant1_added.message is assistant_message1
    assert tool_result_added.message is tool_result_message
    assert user_message2_added.message is user_message2
    assert assistant2_added.message is assistant_message2

    iteration1_end = events[5]
    assert isinstance(iteration1_end, AgentIterationEndEvent)
    assert iteration1_end.termination == "tool_response"
    assert iteration1_end.user_messages == [user_message1]
    assert iteration1_end.assistant_message is assistant_message1
    assert iteration1_end.tool_result_messages == [tool_result_message]

    iteration2_end = events[9]
    assert isinstance(iteration2_end, AgentIterationEndEvent)
    assert iteration2_end.termination == "final_response"
    assert iteration2_end.user_messages == [user_message2]
    assert iteration2_end.assistant_message is assistant_message2
    assert iteration2_end.tool_result_messages is None

    turn_end = events[10]
    assert isinstance(turn_end, AgentTurnEndEvent)
    assert turn_end.termination == "final_response"
    assert len(turn_end.iterations) == 2
    assert turn_end.iterations[0].user_messages == [user_message1]
    assert turn_end.iterations[0].assistant_message is assistant_message1
    assert turn_end.iterations[0].tool_result_messages == [tool_result_message]
    assert turn_end.iterations[1].user_messages == [user_message2]
    assert turn_end.iterations[1].assistant_message is assistant_message2
    assert turn_end.iterations[1].tool_result_messages is None

    assert len(mock_model.generate.outcomes) == 2
    assert len(mock_model.add_user_message.outcomes) == 2
    assert execute.await_args_list[0].args[0] == NoParams()
    assert mock_model.add_tool_result_message.await_args_list[0].args[0] is call_id
    assert mock_model.add_tool_result_message.await_args_list[0].args[1] is tool_result.text

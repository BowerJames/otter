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
from otter_ai_core.types import (
    AssistantMessage,
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


async def test_duplicate_tool_names_raise_at_construction(mock_model: MagicMock) -> None:
    class NoParams(BaseModel):
        pass

    tool_a = create_agent_tool("dup", "first duplicate", NoParams, AsyncMock())
    tool_b = create_agent_tool("dup", "second duplicate", NoParams, AsyncMock())
    with pytest.raises(ValueError):
        Agent(mock_model, tools=[tool_a, tool_b])


async def test_single_turn_agent_loop_events_order(
    mock_model: MagicMock,
) -> None:
    script(mock_model.add_user_message, lambda text: NonCallableMagicMock(spec=UserMessage))

    final = NonCallableMagicMock(spec=AssistantMessage)
    final.stop_reason = "final_response"
    script(mock_model.generate, [final])

    async with mock_model:
        agent = Agent(mock_model, tools=[])
        async with asyncio.timeout(1):
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

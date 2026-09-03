import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from otter_ai_core.abstractions import AgentTool, Model
from otter_ai_core.agent_v2 import (
    Agent,
    AgentTurnStartEvent,
    AgentIterationStartEvent,
    AgentSessionMessageEvent,
    AgentIterationEndEvent,
    AgentTurnEndEvent,
    AgentEvents
    
)
from otter_ai_core.agent_tool_factory import create_agent_tool
from otter_ai_core.types import (
    AgentToolResult,
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


@pytest.fixture
def prompt_text() -> str:
    return "hello"


@pytest.fixture
def model_response() -> AssistantMessage:
    return "world"


@pytest.fixture
def model(prompt_text: str, model_response_text: str) -> Model:
    """Test adapter for the Model seam. Returns a mock satisfying the
    Model interface contract: methods are awaitable within an active
    session and return well-typed messages."""
    model = MagicMock(spec=Model)
    model.__aenter__ = AsyncMock(return_value=model)
    model.__aexit__ = AsyncMock(return_value=None)
    model.add_user_message = AsyncMock(return_value=default_user_message)
    model.add_tool_result_message = AsyncMock(
        return_value=ToolResultMessage(
            id="tool-result-default",
            tool_call_id="tool-call-default",
            content=[TextContent(text="default")],
        )
    )
    model.generate = AsyncMock(return_value=default_assistant_message)
    return model


async def collect(stream: AgentStream, into: list[AgentEvent] | None = None) -> list[AgentEvent]:
    events = [] if into is None else into
    async for event in stream:
        events.append(event)
    return events


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


async def test_duplicate_tool_names_raise_at_construction(model: Model) -> None:
    class NoParams(BaseModel):
        pass

    async def ping(_: NoParams) -> AgentToolResult:
        return AgentToolResult(text="pong")

    tool_a = create_agent_tool("dup", "first duplicate", NoParams, ping)
    tool_b = create_agent_tool("dup", "second duplicate", NoParams, ping)
    with pytest.raises(ValueError):
        Agent(model, tools=[tool_a, tool_b])


async def test_single_turn_agent_loop_events_order(
    model: Model,
) -> None:
    async with model:
        agent = Agent(model, tools=[])
        events = await collect(agent.prompt("hello"))

    assert [type(event) for event in events] == [
        AgentStart,
        AgentTurnStart,
        UserMessage,
        AssistantMessage,
        AgentTurnEnd,
        AgentEnd,
    ]


async def test_user_message_event_is_model_response(
    model: Model, default_user_message: UserMessage
) -> None:
    async with model:
        agent = Agent(model, tools=[])
        events = await collect(agent.prompt("hello"))
    user_message_event = next(event for event in events if isinstance(event, UserMessage))
    assert user_message_event is default_user_message


async def test_assistant_message_event_is_model_response(
    model: Model, default_assistant_message: AssistantMessage
) -> None:
    async with model:
        agent = Agent(model, tools=[])
        events = await collect(agent.prompt("hello"))
        assistant_message_event = next(
            event for event in events if isinstance(event, AssistantMessage)
        )
        assert assistant_message_event is default_assistant_message


async def test_agent_turn_end_event_contains_turn_messages(
    model: Model, default_assistant_message: AssistantMessage, default_user_message: UserMessage
) -> None:
    async with model:
        agent = Agent(model, tools=[])
        events = await collect(agent.prompt("hello"))
        turn_end_event = next(event for event in events if isinstance(event, AgentTurnEnd))
        assert turn_end_event.messages == [default_user_message, default_assistant_message]


class TestSingleTurnBlockingModelActions:
    @pytest.fixture
    def gate(self) -> asyncio.Event:
        return asyncio.Event()

    @pytest.fixture
    def checkpoint(self) -> asyncio.Event:
        return asyncio.Event()

    @pytest.fixture
    def model(
        self,
        gate: asyncio.Event,
        checkpoint: asyncio.Event,
        default_user_message: UserMessage,
        default_assistant_message: AssistantMessage,
    ) -> Model:
        model = MagicMock(spec=Model)
        model.__aenter__ = AsyncMock(return_value=model)
        model.__aexit__ = AsyncMock(return_value=None)

        def gated[TResponse](
            response: TResponse,
        ) -> Callable[..., Coroutine[object, object, TResponse]]:
            async def gated_response(*args: object, **kwargs: object) -> TResponse:
                checkpoint.set()
                await gate.wait()
                gate.clear()
                return response

            return gated_response

        model.add_user_message = AsyncMock(side_effect=gated(default_user_message))
        model.generate = AsyncMock(side_effect=gated(default_assistant_message))
        return model

    @pytest.mark.timeout(5)
    async def test_is_idle_false_while_generating(
        self, model: Model, gate: asyncio.Event, checkpoint: asyncio.Event
    ) -> None:
        async with model:
            agent = Agent(model, tools=[])
            event_stream = agent.prompt("hi")
            assert agent.is_idle() is False
            collection_task = asyncio.create_task(collect(event_stream))

            await checkpoint.wait()  # Wait to reach the add_user_message
            checkpoint.clear()
            assert agent.is_idle() is False
            gate.set()  # Release the add_user_message

            await checkpoint.wait()  # Wait to reach the generate
            checkpoint.clear()
            assert agent.is_idle() is False
            gate.set()  # Release the generate

            await collection_task
            assert agent.is_idle() is True

    @pytest.mark.timeout(5)
    async def test_events_streamed_as_received(
        self, model: Model, gate: asyncio.Event, checkpoint: asyncio.Event
    ) -> None:
        async with model:
            agent = Agent(model, tools=[])
            event_stream = agent.prompt("hi")
            events: list[AgentEvent] = []
            collection_task = asyncio.create_task(collect(event_stream, into=events))
            assert [type(event) for event in events] == []

            await checkpoint.wait()  # Wait to reach the add_user_message
            checkpoint.clear()
            assert [type(event) for event in events] == [AgentStart, AgentTurnStart]
            gate.set()  # Release the add_user_message

            await checkpoint.wait()  # Wait to reach the generate
            checkpoint.clear()
            assert [type(event) for event in events] == [AgentStart, AgentTurnStart, UserMessage]
            gate.set()  # Release the generate

            await collection_task
            assert [type(event) for event in events] == [
                AgentStart,
                AgentTurnStart,
                UserMessage,
                AssistantMessage,
                AgentTurnEnd,
                AgentEnd,
            ]


class TestMutliTurn:
    @pytest.fixture
    def tool_name(self) -> str:
        return "tool-name"

    @pytest.fixture
    def tool_schema(self) -> type[BaseModel]:
        class ABCArgs(BaseModel):
            a: int
            b: str
            c: str | None

        return ABCArgs

    @pytest.fixture
    def tool_result(self) -> AgentToolResult:
        return AgentToolResult(text="tool-result", is_error=False, terminate=False)

    @pytest.fixture
    def tool_execute(
        self, tool_result: AgentToolResult
    ) -> Callable[[object], Awaitable[AgentToolResult]]:
        async def execute(args: object) -> AgentToolResult:
            return tool_result

        return execute

    @pytest.fixture
    def tool(
        self,
        tool_name: str,
        tool_schema: type[BaseModel],
        tool_execute: Callable[[object], Awaitable[AgentToolResult]],
    ) -> AgentTool:

        return create_agent_tool(tool_name, "", tool_schema, tool_execute)

    @pytest.fixture
    def tool_call_assistant_message(self, tool_name: str) -> AssistantMessage:
        return AssistantMessage(
            id="assistant-tool-call-id",
            content=[],
            tool_calls=[
                ToolCall(id="tool-call-id", tool_name=tool_name, parameters={"a": 5, "b": "b"})
            ],
            stop_reason="tool_call",
        )

    @pytest.fixture
    def tool_result_message(self, tool_result: AgentToolResult) -> ToolResultMessage:
        return ToolResultMessage(
            id="tool-result-id",
            tool_call_id="tool-call-id",
            content=[TextContent(text=tool_result.text)],
        )

    @pytest.fixture
    def model(
        self,
        default_user_message: UserMessage,
        default_assistant_message: AssistantMessage,
        tool_call_assistant_message: AssistantMessage,
        tool_result_message: ToolResultMessage,
    ) -> Model:
        model = MagicMock(spec=Model)
        model.__aenter__ = AsyncMock(return_value=model)
        model.__aexit__ = AsyncMock(return_value=None)

        model.add_user_message = AsyncMock(side_effect=[default_user_message])
        model.generate = AsyncMock(
            side_effect=[tool_call_assistant_message, default_assistant_message]
        )
        model.add_tool_result_message = AsyncMock(side_effect=[tool_result_message])
        return model

    async def test_multi_turn_agent_events_order(self, model: Model, tool: AgentTool) -> None:
        async with model:
            agent = Agent(model, tools=[tool])
            event_stream = agent.prompt("hi")
            events = await collect(event_stream)

        assert [type(event) for event in events] == [
            AgentStart,
            AgentTurnStart,
            UserMessage,
            AssistantMessage,
            ToolResultMessage,
            AgentTurnEnd,
            AgentTurnStart,
            UserMessage,
            AssistantMessage,
            AgentTurnEnd,
            AgentEnd,
        ]

import asyncio
from collections.abc import Callable

import pytest

from otter_ai_core.agent_loop import AgentLoopModel
from otter_ai_core.model.fake import FakeModel
from otter_ai_core.model.interface import Model
from otter_ai_core.model.types import (
    AssistantMessage,
    TextContent,
    ToolCall,
)
from otter_ai_core.testing.model_conformance import ModelConformanceMixin

_fake_model_as_agent_loop_model: AgentLoopModel = FakeModel([])


def _final(text: str) -> AssistantMessage:
    return AssistantMessage(
        id=f"assistant-{text}",
        content=[TextContent(text=text)],
        tool_calls=[],
        stop_reason="final_response",
    )


def _tool_call() -> AssistantMessage:
    return AssistantMessage(
        id="assistant-tool-1",
        content=[],
        tool_calls=[
            ToolCall(id="call-1", tool_name="get_weather", parameters={"city": "Leeds"}),
            ToolCall(id="call-2", tool_name="get_time", parameters={"timezone": "UTC"}),
        ],
        stop_reason="tool_call",
    )


class TestFakeModelConformance(ModelConformanceMixin):
    @pytest.fixture
    def make_model(self) -> Callable[[], Model]:
        return lambda: FakeModel([_final("first"), _final("second")])

    @pytest.fixture
    def make_tool_calling_model(self) -> Callable[[], Model]:
        return lambda: FakeModel([_tool_call(), _final("done")])

    @pytest.fixture
    def make_failing_model(self) -> Callable[[], Model]:
        return lambda: FakeModel([])

    @pytest.fixture
    def make_gated_model(self) -> Callable[[], tuple[Model, asyncio.Event]]:
        def factory() -> tuple[Model, asyncio.Event]:
            gate = asyncio.Event()
            model = FakeModel([_final("gated")], generation_gate=gate)
            return model, gate

        return factory

from collections.abc import Callable

import pytest
from pydantic import BaseModel

from otter_ai_core.agent_tool import AgentToolResult, create_agent_tool
from otter_ai_core.agent_tool.conformance import AgentToolConformanceSuite, AgentToolHarness


class EchoParams(BaseModel):
    text: str
    shout: bool = False


class BoomParams(BaseModel):
    text: str


def make_echo_harness() -> AgentToolHarness:
    body_invocations: list[EchoParams] = []

    async def echo(params: EchoParams) -> AgentToolResult:
        body_invocations.append(params)
        body = params.text.upper() if params.shout else params.text
        return AgentToolResult(text=body)

    tool = create_agent_tool("echo", "Echo the text back", EchoParams, echo)
    return AgentToolHarness(
        tool=tool,
        valid_arguments={"text": "hello"},
        invalid_arguments={},
        body_invocations=body_invocations,
    )


def make_boom_harness() -> AgentToolHarness:
    body_invocations: list[BoomParams] = []

    async def boom(params: BoomParams) -> AgentToolResult:
        body_invocations.append(params)
        raise ValueError("the tool body exploded")

    tool = create_agent_tool("boom", "Always raises", BoomParams, boom)
    return AgentToolHarness(
        tool=tool,
        valid_arguments={"text": "hello"},
        invalid_arguments=None,
        body_invocations=body_invocations,
    )


class TestFactoryToolConformance(AgentToolConformanceSuite):
    @pytest.fixture
    def make_tool(self) -> Callable[[], AgentToolHarness]:
        return make_echo_harness

    @pytest.fixture
    def make_raising_tool(self) -> Callable[[], AgentToolHarness]:
        return make_boom_harness

from typing import Any, Literal

import pytest
from pydantic import BaseModel

from otter_ai_core.agent_loop import AgentTool, AgentToolResult, create_agent_tool
from otter_ai_core.model.types import ToolCall


class WeatherParams(BaseModel):
    city: str
    unit: Literal["celsius", "fahrenheit"] = "celsius"


class SearchParams(BaseModel):
    query: str


async def test_execute_validates_dict_and_passes_typed_payload() -> None:
    received: list[WeatherParams] = []

    async def get_weather(params: WeatherParams) -> AgentToolResult:
        received.append(params)
        return AgentToolResult(text=f"weather in {params.city}")

    tool = create_agent_tool("get_weather", "Get the weather", WeatherParams, get_weather)
    result = await tool.execute({"city": "Leeds"})

    assert result == AgentToolResult(text="weather in Leeds")
    assert received == [WeatherParams(city="Leeds", unit="celsius")]


async def test_validation_failure_returns_error_result_without_calling_execute() -> None:
    received: list[WeatherParams] = []

    async def get_weather(params: WeatherParams) -> AgentToolResult:
        received.append(params)
        return AgentToolResult(text="unreachable")

    tool = create_agent_tool("get_weather", "Get the weather", WeatherParams, get_weather)
    result = await tool.execute({"unit": "fahrenheit"})

    assert result.is_error is True
    assert result.terminate is False
    assert "city" in result.text
    assert "get_weather" in result.text
    assert received == []


async def test_callback_exception_propagates() -> None:
    async def get_weather(params: WeatherParams) -> AgentToolResult:
        raise ValueError("the weather service is down")

    tool = create_agent_tool("get_weather", "Get the weather", WeatherParams, get_weather)
    with pytest.raises(ValueError, match="weather service"):
        await tool.execute({"city": "Leeds"})


async def test_hand_written_class_satisfies_protocol_structurally() -> None:
    class EchoTool:
        name = "echo"
        description = "Echoes the query back"
        parameters = SearchParams

        async def execute(self, arguments: dict[str, Any]) -> AgentToolResult:
            payload = SearchParams.model_validate(arguments)
            return AgentToolResult(text=payload.query)

    tool: AgentTool = EchoTool()
    result = await tool.execute({"query": "hello"})
    assert result.text == "hello"
    assert result.is_error is False
    assert result.terminate is False


def test_result_defaults() -> None:
    result = AgentToolResult(text="done")
    assert result.is_error is False
    assert result.terminate is False


async def test_execute_accepts_tool_call_parameters() -> None:
    async def get_weather(params: WeatherParams) -> AgentToolResult:
        return AgentToolResult(text=f"{params.city}:{params.unit}")

    tool = create_agent_tool("get_weather", "Get the weather", WeatherParams, get_weather)
    call = ToolCall(id="call-1", tool_name=tool.name, parameters={"city": "Leeds"})
    result = await tool.execute(call.parameters)
    assert result.text == "Leeds:celsius"


def test_parameters_exposes_json_schema() -> None:
    async def get_weather(params: WeatherParams) -> AgentToolResult:
        return AgentToolResult(text="ok")

    tool = create_agent_tool("get_weather", "Get the weather", WeatherParams, get_weather)
    schema = tool.parameters.model_json_schema()
    assert schema["properties"]["city"]["type"] == "string"
    assert schema["required"] == ["city"]

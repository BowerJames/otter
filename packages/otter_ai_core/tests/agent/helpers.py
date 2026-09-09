from typing import Any
from unittest.mock import NonCallableMagicMock

from otter_ai_core.types import (
    AgentToolResult,
    AssistantMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


def mock_string() -> NonCallableMagicMock:

    s = NonCallableMagicMock(spec=str)

    return s


def mock_user_message() -> NonCallableMagicMock:

    msg = NonCallableMagicMock(spec=UserMessage)

    return msg


def mock_assistant_message(tool_calls: list[ToolCall] | None = None) -> NonCallableMagicMock:
    if tool_calls is None:
        tool_calls = []
    msg = NonCallableMagicMock(spec=AssistantMessage)
    msg.tool_calls = tool_calls
    msg.stop_reason = "final_response" if len(tool_calls) == 0 else "tool_call"

    return msg


def mock_tool_result_message() -> NonCallableMagicMock:

    msg = NonCallableMagicMock(spec=ToolResultMessage)

    return msg


def mock_agent_tool_result(is_error: bool = False, terminate: bool = False) -> NonCallableMagicMock:

    result = NonCallableMagicMock(spec=AgentToolResult)
    result.text = mock_string()
    result.is_error = is_error
    result.terminate = terminate

    return result


def mock_tool_call(id: str, tool_name: str, parameters: dict[str, Any]) -> NonCallableMagicMock:

    call = NonCallableMagicMock(spec=ToolCall)
    call.id = id
    call.tool_name = tool_name
    call.parameters = parameters

    return call

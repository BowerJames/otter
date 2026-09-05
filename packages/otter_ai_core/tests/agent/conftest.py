from collections.abc import Callable
from itertools import count
from unittest.mock import MagicMock

import pytest

from otter_ai_core.abstractions import Model
from otter_ai_core.types import TextContent, ToolResultMessage, UserMessage

from ..support.mock_scripting import script


@pytest.fixture
def echo_user_message() -> Callable[[str], UserMessage]:
    """Default add_user_message behavior: echoes `text` into a UserMessage
    with a sequential id."""
    ids = count(1)

    def echo(text: str) -> UserMessage:
        return UserMessage(id=f"user-{next(ids)}", content=[TextContent(text=text)])

    return echo


@pytest.fixture
def echo_tool_result() -> Callable[[str, str], ToolResultMessage]:
    """Default add_tool_result_message behavior: echoes `text` into a
    ToolResultMessage for `tool_call_id`, with a sequential id."""
    ids = count(1)

    def echo(tool_call_id: str, text: str) -> ToolResultMessage:
        return ToolResultMessage(
            id=f"tool-result-{next(ids)}",
            tool_call_id=tool_call_id,
            content=[TextContent(text=text)],
        )

    return echo


@pytest.fixture
def model(
    mock_model: MagicMock,
    echo_user_message: Callable[[str], UserMessage],
    echo_tool_result: Callable[[str, str], ToolResultMessage],
) -> Model:
    """Model for driving the agent: the package mock_model substrate with
    echo defaults on the message methods and an empty generate script.

    Tests declare their generations by re-scripting generate (for example
    ``script(mock_model.generate, [assistant_message])`` — ``mock_model``
    and ``model`` are the same object) and inspect calls and outcomes
    through the standard mock attributes."""
    script(mock_model.add_user_message, echo_user_message)
    script(mock_model.add_tool_result_message, echo_tool_result)
    script(mock_model.generate, [])
    return mock_model

from unittest.mock import MagicMock

import pytest

from otter_ai_core.abstractions import Model
from otter_ai_core.types import AssistantMessage, TextContent

from ..support.mock_scripting import ScriptExhausted, script


async def test_model_add_user_message_echoes_input(model: Model) -> None:
    async with model:
        first = await model.add_user_message("hello")
        second = await model.add_user_message("again")

    assert first.content == [TextContent(text="hello")]
    assert second.content == [TextContent(text="again")]
    assert first.id != second.id


async def test_model_add_tool_result_echoes_input(model: Model) -> None:
    async with model:
        result = await model.add_tool_result_message("call-1", "payload")

    assert result.tool_call_id == "call-1"
    assert result.content == [TextContent(text="payload")]


async def test_model_generate_fails_loudly_until_scripted(model: Model) -> None:
    async with model:
        with pytest.raises(ScriptExhausted):
            await model.generate()


async def test_model_generate_is_scriptable_per_test(model: Model, mock_model: MagicMock) -> None:
    final = AssistantMessage(
        id="a-1", content=[TextContent(text="done")], tool_calls=[], stop_reason="final_response"
    )
    script(mock_model.generate, [final])

    async with model:
        assert await model.generate() is final
        assert mock_model.generate.outcomes == [final]

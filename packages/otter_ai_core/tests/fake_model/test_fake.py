import pytest

from otter_ai_core.conversation import (
    AssistantMessage,
    TextContent,
    ToolResultMessage,
)
from otter_ai_core.fake_model import FakeModel, FakeModelExhausted
from otter_ai_core.model import Model


def _assistant_text(text: str) -> AssistantMessage:
    return AssistantMessage(
        id=f"assistant-{text}",
        content=[TextContent(text=text)],
        tool_calls=[],
        stop_reason="final_response",
    )


async def test_fake_model_conforms_to_model_interface() -> None:
    model: Model = FakeModel([_assistant_text("hello")])
    async with model:
        await model.generate()


async def test_add_user_message_returns_user_message_with_text() -> None:
    model = FakeModel([])
    async with model:
        message = await model.add_user_message("hello")
    assert message.role == "user"
    assert message.content == [TextContent(text="hello")]


async def test_generate_returns_scripted_responses_in_order() -> None:
    model = FakeModel([_assistant_text("first"), _assistant_text("second")])
    async with model:
        first = await model.generate()
        second = await model.generate()
    assert first.content[0].text == "first"
    assert second.content[0].text == "second"


async def test_generate_beyond_script_raises_exhausted() -> None:
    model = FakeModel([_assistant_text("only")])
    async with model:
        await model.generate()
        with pytest.raises(FakeModelExhausted):
            await model.generate()


async def test_methods_called_outside_session_raise() -> None:
    model = FakeModel([_assistant_text("hello")])
    with pytest.raises(RuntimeError):
        await model.add_user_message("hello")
    with pytest.raises(RuntimeError):
        await model.generate()


async def test_session_cannot_be_reentered() -> None:
    model = FakeModel([_assistant_text("hello")])
    async with model:
        await model.generate()
    with pytest.raises(RuntimeError):
        await model.__aenter__()


async def test_history_records_messages_in_order() -> None:
    model = FakeModel([_assistant_text("reply")])
    async with model:
        await model.add_user_message("hello")
        await model.generate()
        await model.add_tool_result_message("assistant-reply", "result")
    assert [type(message).__name__ for message in model.history] == [
        "UserMessage",
        "AssistantMessage",
        "ToolResultMessage",
    ]
    tool_result = model.history[2]
    assert isinstance(tool_result, ToolResultMessage)
    assert tool_result.tool_call_id == "assistant-reply"

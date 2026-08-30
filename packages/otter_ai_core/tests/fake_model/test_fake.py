import asyncio

import pytest

from otter_ai_core.fake_model import FakeModel, FakeModelExhausted
from otter_ai_core.types import (
    AssistantMessage,
    TextContent,
    ToolResultMessage,
)


def _assistant_text(text: str) -> AssistantMessage:
    return AssistantMessage(
        id=f"assistant-{text}",
        content=[TextContent(text=text)],
        tool_calls=[],
        stop_reason="final_response",
    )


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


async def test_methods_are_gated_by_session_lifecycle() -> None:
    model = FakeModel([_assistant_text("reply")])
    with pytest.raises(RuntimeError):
        await model.add_user_message("hello")
    with pytest.raises(RuntimeError):
        await model.add_tool_result_message("call", "result")
    with pytest.raises(RuntimeError):
        await model.generate()

    async with model:
        await model.add_user_message("hello")

    with pytest.raises(RuntimeError):
        await model.add_user_message("again")
    with pytest.raises(RuntimeError):
        await model.add_tool_result_message("call", "result")
    with pytest.raises(RuntimeError):
        await model.generate()


async def test_generate_gating_and_concurrency() -> None:
    gate = asyncio.Event()
    model = FakeModel([_assistant_text("reply")], generation_gate=gate)

    async with model:
        first = asyncio.create_task(model.generate())
        await asyncio.sleep(0)  # first generate reaches the gate and waits
        with pytest.raises(RuntimeError):
            await model.generate()

        gate.set()
        assert (await first).content[0].text == "reply"


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

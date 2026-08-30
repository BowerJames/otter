import asyncio
from typing import cast

import pytest

from otter_ai_core.stub_model import StubModel, StubNotSeeded
from otter_ai_core.types import AssistantMessage, ToolResultMessage, UserMessage


def test_stub_model_constructed() -> None:
    StubModel()


async def test_stub_model_raises_if_not_entered() -> None:
    model = StubModel()

    with pytest.raises(RuntimeError):
        await model.add_user_message("hello")
    with pytest.raises(RuntimeError):
        await model.add_tool_result_message("call", "result")
    with pytest.raises(RuntimeError):
        await model.generate()


async def test_stub_model_raises_if_not_seeded() -> None:
    model = StubModel()
    async with model:
        with pytest.raises(StubNotSeeded):
            await model.add_user_message("hello")
        with pytest.raises(StubNotSeeded):
            await model.add_tool_result_message("call", "result")
        with pytest.raises(StubNotSeeded):
            await model.generate()


async def test_stub_model_can_be_seed_user_message() -> None:
    model = StubModel()
    user_message = cast(UserMessage, object())
    async with model:
        event = model.seed_user_message(user_message)
        task = asyncio.create_task(model.add_user_message("hi"))
        await asyncio.sleep(0)
        assert not task.done()
        event.set()
        await asyncio.sleep(0)
        assert task.done()
        message = await task
        assert message is user_message


async def test_stub_model_can_seed_generate() -> None:
    model = StubModel()
    assistant = cast(AssistantMessage, object())
    async with model:
        event = model.seed_generate(assistant)
        task = asyncio.create_task(model.generate())
        await asyncio.sleep(0)
        assert not task.done()
        event.set()
        await asyncio.sleep(0)
        assert task.done()
        message = await task
        assert message is assistant


async def test_stub_model_can_seed_tool_result_message() -> None:
    model = StubModel()
    tool_result = cast(ToolResultMessage, object())
    async with model:
        event = model.seed_tool_result_message(tool_result)
        task = asyncio.create_task(model.add_tool_result_message("c1", "result"))
        await asyncio.sleep(0)
        assert not task.done()
        event.set()
        await asyncio.sleep(0)
        assert task.done()
        message = await task
        assert message is tool_result


async def test_stub_model_consumes_seeds_in_seeding_order() -> None:
    model = StubModel()
    first = cast(UserMessage, object())
    second = cast(UserMessage, object())
    async with model:
        first_event = model.seed_user_message(first)
        second_event = model.seed_user_message(second)
        first_event.set()
        second_event.set()
        assert await model.add_user_message("one") is first
        assert await model.add_user_message("two") is second

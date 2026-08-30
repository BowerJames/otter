import asyncio

import pytest

from otter_ai_core.stub_model import StubModel, StubNotSeeded


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
    user_text = "hi"
    async with model:
        event, UserMessage = model.seed_user_message(text=user_text)
        task = asyncio.create_task(model.add_user_message(user_text))
        await asyncio.sleep(0)
        assert not task.done()
        event.set()
        await asyncio.sleep(0)
        assert task.done()
        message = await task
        assert message is UserMessage

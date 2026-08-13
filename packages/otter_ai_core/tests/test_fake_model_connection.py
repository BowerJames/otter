from __future__ import annotations

import asyncio

import pytest

from otter_ai_core.data_models.context import TextContent
from otter_ai_core.data_models.events.server_context_events import ServerContextEvent, UserItemAdded
from otter_ai_core.mock.model_connection import FakeModelConnection


async def _drain(
    connection: FakeModelConnection, into: asyncio.Queue[ServerContextEvent] | None = None
) -> None:
    async for event in connection:
        if into is not None:
            into.put_nowait(event)


class TestConstruction:
    def test_fake_model_connection_init(self) -> None:
        FakeModelConnection()


class TestIsIdle:
    def test_fake_model_connection_is_idle_by_default(self) -> None:
        connection = FakeModelConnection()
        assert connection.is_idle()

    def test_fake_model_connection_can_be_constructed_idle(self) -> None:
        connection = FakeModelConnection(idle=True)
        assert connection.is_idle()

    def test_fake_model_connection_can_be_constructed_busy(self) -> None:
        connection = FakeModelConnection(idle=False)
        assert not connection.is_idle()


class TestTriggerEnd:
    async def test_raises_if_auto_end_is_true(self) -> None:
        connection = FakeModelConnection(auto_end=True)
        task = asyncio.create_task(_drain(connection))
        connection.end()
        with pytest.raises(RuntimeError):
            connection.trigger_end()
        await asyncio.sleep(0)
        assert task.done()
        await task

    async def test_raises_if_end_not_called(self) -> None:
        connection = FakeModelConnection(auto_end=False)
        task = asyncio.create_task(_drain(connection))
        with pytest.raises(RuntimeError):
            connection.trigger_end()
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_ends_stream(self) -> None:
        connection = FakeModelConnection(auto_end=False)
        task = asyncio.create_task(_drain(connection))
        connection.end()
        connection.trigger_end()
        await asyncio.sleep(0)
        assert task.done()
        await task


class TestAutoEnd:
    async def test_auto_end_ends_stream(self) -> None:
        connection = FakeModelConnection(auto_end=True)
        task = asyncio.create_task(_drain(connection))
        connection.end()
        await asyncio.sleep(0)
        assert task.done()
        await task


class TestAutoAddUserItem:
    @staticmethod
    @pytest.fixture(scope="class")
    def inbound_queue() -> asyncio.Queue[ServerContextEvent]:
        return asyncio.Queue()

    async def test_auto_add_automatically_responds(
        self, inbound_queue: asyncio.Queue[ServerContextEvent]
    ) -> None:
        connection = FakeModelConnection(auto_add_user_item=True)
        task = asyncio.create_task(_drain(connection, inbound_queue))
        message = "lorem ipsum"
        connection.add_user_message(message)
        await asyncio.sleep(0)
        event = inbound_queue.get_nowait()
        assert isinstance(event, UserItemAdded)
        with pytest.raises(asyncio.QueueEmpty):
            inbound_queue.get_nowait()
        assert not task.done()
        text_content = event.item.message.content[0]
        assert isinstance(text_content, TextContent)
        assert text_content.text == message
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

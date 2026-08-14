from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator

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


@contextlib.asynccontextmanager
async def streaming(
    connection: FakeModelConnection, into: asyncio.Queue[ServerContextEvent] | None = None
) -> AsyncGenerator[asyncio.Task[None], None]:
    task = asyncio.create_task(_drain(connection, into))
    try:
        yield task
    finally:
        if task.done():
            await task
        else:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


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
        async with streaming(connection) as task:
            connection.end()
            with pytest.raises(RuntimeError):
                connection.trigger_end()
            await asyncio.sleep(0)
            assert task.done()

    async def test_raises_if_end_not_called(self) -> None:
        connection = FakeModelConnection(auto_end=False)
        async with streaming(connection) as task:
            with pytest.raises(RuntimeError):
                connection.trigger_end()
            await asyncio.sleep(0)
            assert not task.done()

    async def test_ends_stream(self) -> None:
        connection = FakeModelConnection(auto_end=False)
        async with streaming(connection) as task:
            connection.end()
            connection.trigger_end()
            await asyncio.sleep(0)
            assert task.done()


class TestAutoEnd:
    async def test_auto_end_ends_stream(self) -> None:
        connection = FakeModelConnection(auto_end=True)
        async with streaming(connection) as task:
            connection.end()
            await asyncio.sleep(0)
            assert task.done()


class TestAutoAddUserItem:
    async def test_auto_add_automatically_responds(self) -> None:
        connection = FakeModelConnection(auto_add_user_item=True)
        inbound_queue: asyncio.Queue[ServerContextEvent] = asyncio.Queue()
        async with streaming(connection, inbound_queue) as task:
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

    async def test_auto_add_disabled_does_not_respond(self) -> None:
        connection = FakeModelConnection(auto_add_user_item=False)
        inbound_queue: asyncio.Queue[ServerContextEvent] = asyncio.Queue()
        async with streaming(connection, inbound_queue) as task:
            message = "lorem ipsum"
            connection.add_user_message(message)
            await asyncio.sleep(0)
            with pytest.raises(asyncio.QueueEmpty):
                inbound_queue.get_nowait()
            assert not task.done()


class TestConfirmUserMessage:
    def test_confirm_user_message_raises_with_auto_add_enabled(self) -> None:
        connection = FakeModelConnection(auto_add_user_item=True)
        with pytest.raises(RuntimeError):
            connection.confirm_user_message("test")

    async def test_confirm_user_message_adds_user_item(self) -> None:
        connection = FakeModelConnection(auto_add_user_item=False)
        inbound_queue: asyncio.Queue[ServerContextEvent] = asyncio.Queue()
        async with streaming(connection, inbound_queue) as task:
            message = "lorem ipsum"
            connection.add_user_message(message)
            connection.confirm_user_message(message)
            await asyncio.sleep(0)
            event = inbound_queue.get_nowait()
            assert isinstance(event, UserItemAdded)
            text_content = event.item.message.content[0]
            assert isinstance(text_content, TextContent)
            assert text_content.text == message
            with pytest.raises(asyncio.QueueEmpty):
                inbound_queue.get_nowait()
            assert not task.done()

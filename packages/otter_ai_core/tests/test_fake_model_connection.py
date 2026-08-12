from __future__ import annotations

import asyncio

import pytest

from otter_ai_core.mock.model_connection import FakeModelConnection


@pytest.fixture(scope="module")
def connection() -> FakeModelConnection:
    return FakeModelConnection()


async def _stream(connection: FakeModelConnection) -> None:
    async for _ in connection:
        pass


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
        task = asyncio.create_task(_stream(connection))
        connection.end()
        with pytest.raises(RuntimeError):
            connection.trigger_end()
        await asyncio.sleep(0)
        assert task.done()
        await task

    async def test_raises_if_end_not_called(self) -> None:
        connection = FakeModelConnection(auto_end=False)
        task = asyncio.create_task(_stream(connection))
        with pytest.raises(RuntimeError):
            connection.trigger_end()
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_ends_stream(self) -> None:
        connection = FakeModelConnection(auto_end=False)
        task = asyncio.create_task(_stream(connection))
        connection.end()
        connection.trigger_end()
        await asyncio.sleep(0)
        assert task.done()
        await task


class TestAutoEnd:
    async def test_auto_end_ends_stream(self) -> None:
        connection = FakeModelConnection(auto_end=True)
        task = asyncio.create_task(_stream(connection))
        connection.end()
        await asyncio.sleep(0)
        assert task.done()
        await task

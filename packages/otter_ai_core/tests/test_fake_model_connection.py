from __future__ import annotations

import asyncio

import pytest

from otter_ai_core.mock.model_connection import FakeModelConnection


@pytest.fixture(autouse=True)
def fake_model_connection() -> FakeModelConnection:
    return FakeModelConnection()


async def _stream(connection: FakeModelConnection) -> None:
    async for _ in connection:
        pass


class TestConstruction:
    def test_fake_model_connection_init(self) -> None:
        FakeModelConnection()

    def test_fake_model_connection_is_idle_by_default(self) -> None:
        connection = FakeModelConnection()
        assert connection.is_idle()

    def test_fake_model_connection_can_be_constructed_idle(self) -> None:
        connection = FakeModelConnection(idle=True)
        assert connection.is_idle()

    def test_fake_model_connection_can_be_constructed_busy(self) -> None:
        connection = FakeModelConnection(idle=False)
        assert not connection.is_idle()


class TestEnd:
    async def test_fake_model_connection_does_not_end_automatically(
        self,
        fake_model_connection: FakeModelConnection,
    ) -> None:

        task = asyncio.create_task(_stream(fake_model_connection))
        fake_model_connection.end()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(task, 1)

    async def test_fake_model_connection_can_trigger_end(
        self,
        fake_model_connection: FakeModelConnection,
    ) -> None:

        task = asyncio.create_task(_stream(fake_model_connection))
        fake_model_connection.end()
        fake_model_connection.trigger_end()
        await asyncio.wait_for(task, 1)

from __future__ import annotations

import asyncio

import pytest

from otter_ai_core.mock.model_connection import FakeModelConnection


@pytest.fixture(autouse=True)
def fake_model_connection() -> FakeModelConnection:
    return FakeModelConnection()


def test_fake_model_connection_init() -> None:
    FakeModelConnection()


async def test_fake_model_connection_can_end(
    fake_model_connection: FakeModelConnection,
) -> None:
    async def stream(connection: FakeModelConnection) -> None:
        async for _ in connection:
            pass

    task = asyncio.create_task(stream(fake_model_connection))
    fake_model_connection.end()
    await task

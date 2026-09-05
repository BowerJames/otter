from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from otter_ai_core.abstractions import Model


async def test_mock_model_methods_are_awaitable(mock_model: Model) -> None:
    """Pins the reason the fixture installs AsyncMocks explicitly: the
    Model protocol's methods are plain `def -> Awaitable[...]`, so a
    spec'd mock alone would give non-awaitable MagicMock children."""
    async with mock_model:
        await mock_model.add_user_message("hi")
        await mock_model.add_tool_result_message("call", "result")
        await mock_model.generate()


def test_mock_model_methods_are_async_mocks(mock_model: Model) -> None:
    assert isinstance(mock_model.add_user_message, AsyncMock)
    assert isinstance(mock_model.add_tool_result_message, AsyncMock)
    assert isinstance(mock_model.generate, AsyncMock)


def test_mock_model_is_spec_enforced(mock_model: Model) -> None:
    with pytest.raises(AttributeError):
        cast(MagicMock, mock_model).not_a_model_method  # noqa: B018

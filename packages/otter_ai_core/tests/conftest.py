from unittest.mock import AsyncMock, MagicMock

import pytest

from otter_ai_core.abstractions import Model


@pytest.fixture
def mock_model() -> Model:
    """Plain Model mock: spec-enforced, session-wired, nothing scripted.

    The interface methods are installed as fresh AsyncMocks explicitly:
    the Model protocol declares them as plain ``def -> Awaitable[...]``
    (not ``async def``), so ``MagicMock(spec=Model)`` does not configure
    them as awaitable on its own. Script them with
    ``tests.support.mock_scripting.script`` — or overwrite them — before
    driving behaviour through the mock.
    """
    model = MagicMock(spec=Model)
    model.__aenter__ = AsyncMock(return_value=model)
    model.__aexit__ = AsyncMock(return_value=None)
    model.add_user_message = AsyncMock()
    model.add_tool_result_message = AsyncMock()
    model.generate = AsyncMock()
    return model

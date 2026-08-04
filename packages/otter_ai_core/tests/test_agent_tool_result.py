from __future__ import annotations

import sys

import pytest
from pydantic import ValidationError

from otter_ai_core import ImageContent, TextContent
from otter_ai_core.data_models import AgentToolResult


def test_defaults_are_false() -> None:
    r = AgentToolResult[str](result=[], details="ok")
    assert r.is_error is False
    assert r.terminate is False


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        AgentToolResult[str].model_validate({"result": [], "details": "ok", "unexpected": 1})


def test_result_accepts_user_content_union() -> None:
    r = AgentToolResult[int](
        result=[
            TextContent(type="text", text="hi"),
            ImageContent(type="image", data="AAAA", mime_type="image/png"),
        ],
        details=0,
    )
    assert isinstance(r.result[0], TextContent)
    assert isinstance(r.result[1], ImageContent)


def test_interfaces_does_not_import_agent_loop() -> None:
    sys.modules.pop("otter_ai_core.agent_loop", None)
    import otter_ai_core.interfaces.agent_tool  # noqa: F401

    assert "otter_ai_core.agent_loop" not in sys.modules

"""Tests for the ``session.update`` body assembly."""

from __future__ import annotations

from typing import Any

from _realtime_helpers import make_options

from otter_ai_core import Tool
from otter_ai_realtime._session import build_session_body, build_session_update
from otter_ai_realtime.hooks import OnSessionUpdateEvent
from otter_ai_realtime.models import RealtimeSessionConfig


def test_session_body_includes_instructions_and_tools() -> None:
    options = make_options()
    tool = Tool(
        name="get_weather", description="Get weather", parameters={"type": "object"}
    )
    body = build_session_body(options, "You are helpful.", [tool])
    assert body["instructions"] == "You are helpful."
    assert body["tools"] == [
        {
            "type": "function",
            "name": "get_weather",
            "description": "Get weather",
            "parameters": {"type": "object"},
        }
    ]


def test_session_body_omits_unset_config_fields() -> None:
    options = make_options()  # default empty session config
    body = build_session_body(options, None, [])
    # No instructions (None prompt), no tools, no config keys.
    assert body == {}


def test_session_body_emits_only_set_config_fields() -> None:
    options = make_options(
        session_config=RealtimeSessionConfig(
            voice="alloy",
            modalities=["text"],
            temperature=0.5,
        )
    )
    body = build_session_body(options, "hi", [])
    assert body["voice"] == "alloy"
    assert body["modalities"] == ["text"]
    assert body["temperature"] == 0.5
    # Fields left None are omitted.
    assert "max_response_output_tokens" not in body
    assert "turn_detection" not in body


def test_build_session_update_wraps_in_frame() -> None:
    options = make_options()
    frame = build_session_update(options, "instructions", [])
    assert frame["type"] == "session.update"
    assert frame["session"]["instructions"] == "instructions"


async def test_on_session_update_hook_can_replace_body() -> None:
    options = make_options()

    async def replace(event: OnSessionUpdateEvent) -> dict[str, Any]:
        return {"custom": True}

    options.hooks.on_session_update = replace
    # The seam uses build_session_body then applies the hook; simulate that.
    body = build_session_body(options, "sys", [])
    replaced = await options.hooks.on_session_update(
        OnSessionUpdateEvent(session=body, model=options.model)
    )
    assert replaced == {"custom": True}

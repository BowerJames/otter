"""Tests for Context → Realtime item/tool translation."""

from __future__ import annotations

import json

import pytest
from _realtime_helpers import user_text

from otter_ai_core import (
    AssistantMessage,
    ImageContent,
    StopReason,
    TextContent,
    Tool,
    ToolCall,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserMessage,
)
from otter_ai_realtime._messages import (
    convert_items,
    convert_items_to_create_frames,
    convert_tools,
)


def test_convert_tools_flattens_name_description_parameters() -> None:
    tools = [
        Tool(name="a", description="desc", parameters={"type": "object"}),
    ]
    assert convert_tools(tools) == [
        {
            "type": "function",
            "name": "a",
            "description": "desc",
            "parameters": {"type": "object"},
        }
    ]


def test_convert_user_message_uses_input_text() -> None:
    items = convert_items([user_text("hello")])
    assert items == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "hello"}],
        }
    ]


def test_convert_assistant_message_emits_message_then_function_calls() -> None:
    msg = AssistantMessage(
        role="assistant",
        content=[
            TextContent(type="text", text="ok"),
            ToolCall(type="tool_call", id="call_1", name="get", arguments={"q": "x"}),
        ],
        api="realtime",
        provider="openai",
        model="gpt-4o-realtime",
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost=UsageCost(input=0, output=0, cache_read=0, cache_write=0, total=0),
        ),
        stop_reason=StopReason.Stop,
        timestamp=0,
    )
    items = convert_items([msg])
    assert items[0] == {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "ok"}],
    }
    assert items[1]["type"] == "function_call"
    assert items[1]["call_id"] == "call_1"
    assert items[1]["name"] == "get"
    assert json.loads(items[1]["arguments"]) == {"q": "x"}


def test_convert_tool_result_uses_function_call_output() -> None:
    msg = ToolResultMessage(
        role="tool_result",
        tool_call_id="call_1",
        tool_name="get",
        content=[TextContent(type="text", text="result")],
        is_error=False,
        timestamp=0,
    )
    items = convert_items([msg])
    assert items == [
        {"type": "function_call_output", "call_id": "call_1", "output": "result"}
    ]


def test_normalize_messages_runs_first_dropping_errored_turns() -> None:
    bad = AssistantMessage(
        role="assistant",
        content=[TextContent(type="text", text="x")],
        api="realtime",
        provider="openai",
        model="m",
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost=UsageCost(input=0, output=0, cache_read=0, cache_write=0, total=0),
        ),
        stop_reason=StopReason.Error,
        timestamp=0,
    )
    good = user_text("hi")
    # Errored assistant turn is dropped by normalize_messages.
    items = convert_items([bad, good])
    assert items == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "hi"}],
        }
    ]


def test_image_content_raises_in_user_message() -> None:
    msg = UserMessage(
        role="user",
        content=[ImageContent(type="image", data="b64", mime_type="image/png")],
        timestamp=0,
    )
    with pytest.raises(ValueError, match="text-only"):
        convert_items([msg])


def test_orphan_tool_call_gets_synthetic_result() -> None:
    call = AssistantMessage(
        role="assistant",
        content=[ToolCall(type="tool_call", id="c1", name="n", arguments={})],
        api="realtime",
        provider="openai",
        model="m",
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost=UsageCost(input=0, output=0, cache_read=0, cache_write=0, total=0),
        ),
        stop_reason=StopReason.ToolUse,
        timestamp=0,
    )
    items = convert_items([call])
    # function_call + a synthetic function_call_output (filled by normalize).
    assert items[0]["type"] == "function_call"
    assert items[1]["type"] == "function_call_output"
    assert items[1]["call_id"] == "c1"


def test_convert_items_to_create_frames_wraps_each_item() -> None:
    frames = convert_items_to_create_frames([user_text("hi")])
    assert frames == [
        {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hi"}],
            },
        }
    ]

"""Construction and validation of the context data model."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from otter_ai import (
    AssistantMessage,
    Context,
    ImageContent,
    TextContent,
    ThinkingContent,
    Tool,
    ToolCall,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserMessage,
)


def _usage() -> Usage:
    return Usage(
        input=10,
        output=5,
        cache_read=0,
        cache_write=0,
        total_tokens=15,
        cost=UsageCost(
            input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0
        ),
    )


def _assistant(**overrides: Any) -> AssistantMessage:
    base = {
        "role": "assistant",
        "content": [TextContent(type="text", text="hi")],
        "api": "anthropic-messages",
        "provider": "anthropic",
        "model": "claude-3",
        "usage": _usage(),
        "stop_reason": "stop",
        "timestamp": 1,
    }
    base.update(overrides)
    return AssistantMessage(**base)


def test_user_message_plain_string_content() -> None:
    msg = UserMessage(role="user", content="hello", timestamp=0)
    assert msg.content == "hello"


def test_user_message_multimodal_content() -> None:
    msg = UserMessage(
        role="user",
        content=[
            TextContent(type="text", text="look"),
            ImageContent(type="image", data="AAAA", mime_type="image/png"),
        ],
        timestamp=0,
    )
    assert isinstance(msg.content[1], ImageContent)


def test_assistant_message_minimal() -> None:
    msg = _assistant()
    assert msg.response_model is None
    assert msg.diagnostics is None
    assert msg.error_message is None


def test_assistant_message_tool_call_block() -> None:
    msg = _assistant(
        content=[
            ThinkingContent(type="thinking", thinking="hmm"),
            ToolCall(type="tool_call", id="t1", name="get_time", arguments={}),
        ]
    )
    assert isinstance(msg.content[1], ToolCall)


def test_tool_result_message() -> None:
    msg = ToolResultMessage(
        role="tool_result",
        tool_call_id="t1",
        tool_name="get_time",
        content=[TextContent(type="text", text="12:00")],
        is_error=False,
        timestamp=2,
    )
    assert msg.details is None


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        TextContent(type="text", text="hi", unexpected="boom")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Usage(
            input=1,
            output=1,
            cache_read=0,
            cache_write=0,
            total_tokens=2,
            cost=UsageCost(input=0, output=0, cache_read=0, cache_write=0, total=0),
            bogus=1,  # type: ignore[call-arg]
        )


def test_discriminated_union_dispatch_assistant() -> None:
    ctx = Context.model_validate(
        {
            "system_prompt": "s",
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "hi"}],
                    "api": "anthropic-messages",
                    "provider": "anthropic",
                    "model": "claude-3",
                    "usage": {
                        "input": 1,
                        "output": 1,
                        "cache_read": 0,
                        "cache_write": 0,
                        "total_tokens": 2,
                        "cost": {
                            "input": 0,
                            "output": 0,
                            "cache_read": 0,
                            "cache_write": 0,
                            "total": 0,
                        },
                    },
                    "stop_reason": "stop",
                    "timestamp": 1,
                }
            ],
        }
    )
    assert isinstance(ctx.messages[0], AssistantMessage)


def test_unknown_role_rejected() -> None:
    with pytest.raises(ValidationError):
        Context.model_validate(
            {"messages": [{"role": "system", "content": "x", "timestamp": 0}]}
        )


def test_unknown_content_type_rejected() -> None:
    with pytest.raises(ValidationError):
        UserMessage.model_validate(
            {
                "role": "user",
                "content": [{"type": "audio", "text": "x"}],
                "timestamp": 0,
            }
        )


def test_invalid_stop_reason_rejected() -> None:
    with pytest.raises(ValidationError):
        _assistant(stop_reason="bogus")


def test_tool_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        Tool(name="t", description="d", parameters={"type": "object"}, extra="x")  # type: ignore[call-arg]


def test_context_defaults() -> None:
    ctx = Context()
    assert ctx.system_prompt is None
    assert ctx.messages == []
    assert ctx.tools is None

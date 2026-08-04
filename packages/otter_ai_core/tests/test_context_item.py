"""Unit tests for context items and the ``context_item`` dispatcher."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from otter_ai_core import (
    AssistantContextItem,
    AssistantMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultContextItem,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserContextItem,
    UserMessage,
    context_item,
)
from otter_ai_core.data_models.context import Role


def _usage() -> Usage:
    return Usage(
        input=10,
        output=5,
        cache_read=0,
        cache_write=0,
        total_tokens=15,
        cost=UsageCost(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0),
    )


def _user() -> UserMessage:
    return UserMessage(role="user", content="hello", timestamp=0)


def _assistant() -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[
            ThinkingContent(type="thinking", thinking="hmm"),
            ToolCall(type="tool_call", id="t1", name="get_time", arguments={}),
            TextContent(type="text", text="hi"),
        ],
        api="anthropic-messages",
        provider="anthropic",
        model="claude-3",
        response_model="claude-3-real",
        response_id="resp_1",
        usage=_usage(),
        stop_reason="tool_use",
        timestamp=1,
    )


def _tool_result() -> ToolResultMessage:
    return ToolResultMessage(
        role="tool_result",
        tool_call_id="t1",
        tool_name="get_time",
        content=[TextContent(type="text", text="12:00")],
        details={"raw": 1234},
        is_error=False,
        timestamp=2,
    )


# --------------------------------------------------------------------------- #
# subclass construction wraps the message under ``message``
# --------------------------------------------------------------------------- #


def test_user_item_wraps_message() -> None:
    msg = _user()
    item = UserContextItem(id="u1", message=msg)
    assert isinstance(item, UserContextItem)
    assert item.id == "u1"
    assert item.message == msg
    assert item.message.role == Role.User


def test_assistant_item_wraps_message() -> None:
    msg = _assistant()
    item = AssistantContextItem(id="a1", message=msg)
    assert isinstance(item, AssistantContextItem)
    assert item.id == "a1"
    assert item.message == msg
    assert item.message.role == Role.Assistant
    assert item.message.model == msg.model
    assert item.message.usage == msg.usage


def test_tool_result_item_wraps_message() -> None:
    msg = _tool_result()
    item = ToolResultContextItem(id="t1", message=msg)
    assert isinstance(item, ToolResultContextItem)
    assert item.id == "t1"
    assert item.message == msg
    assert item.message.is_error is False
    assert item.message.details == {"raw": 1234}


# --------------------------------------------------------------------------- #
# variants are distinct subclasses (isinstance discriminates)
# --------------------------------------------------------------------------- #


def test_variants_are_distinct_subclasses() -> None:
    user = UserContextItem(id="u1", message=_user())
    asst = AssistantContextItem(id="a1", message=_assistant())
    tool = ToolResultContextItem(id="t1", message=_tool_result())

    assert isinstance(user, UserContextItem)
    assert not isinstance(user, AssistantContextItem)
    assert not isinstance(user, ToolResultContextItem)

    assert isinstance(asst, AssistantContextItem)
    assert not isinstance(asst, UserContextItem)

    assert isinstance(tool, ToolResultContextItem)
    assert not isinstance(tool, UserContextItem)


def test_item_rejects_unknown_top_level_fields() -> None:
    """``extra="forbid"`` on ``BaseContextItem`` rejects stray top-level fields."""
    with pytest.raises(ValidationError):
        UserContextItem.model_validate({"id": "u1", "message": _user().model_dump(), "bogus": 1})


# --------------------------------------------------------------------------- #
# context_item() dispatcher
# --------------------------------------------------------------------------- #


def test_context_item_dispatches_by_role() -> None:
    assert isinstance(context_item(message=_user(), id="u1"), UserContextItem)
    assert isinstance(context_item(message=_assistant(), id="a1"), AssistantContextItem)
    assert isinstance(context_item(message=_tool_result(), id="t1"), ToolResultContextItem)


def test_context_item_preserves_message() -> None:
    for msg in (_user(), _assistant(), _tool_result()):
        assert context_item(message=msg, id="x").message == msg

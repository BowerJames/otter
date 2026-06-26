"""Unit tests for the context-item helpers: ``to_message``, ``from_message``,
and the ``context_item`` dispatcher."""

from __future__ import annotations

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
# from_message
# --------------------------------------------------------------------------- #


def test_from_message_user_preserves_fields_and_sets_id() -> None:
    msg = _user()
    item = UserContextItem.from_message(msg, id="u1")
    assert isinstance(item, UserContextItem)
    assert item.id == "u1"
    assert item.role == "user"
    assert item.content == msg.content
    assert item.timestamp == msg.timestamp


def test_from_message_assistant_preserves_fields_and_sets_id() -> None:
    msg = _assistant()
    item = AssistantContextItem.from_message(msg, id="a1")
    assert isinstance(item, AssistantContextItem)
    assert item.id == "a1"
    assert item.role == "assistant"
    assert item.content == msg.content
    assert item.model == msg.model
    assert item.response_model == msg.response_model
    assert item.usage == msg.usage


def test_from_message_tool_result_preserves_fields_and_sets_id() -> None:
    msg = _tool_result()
    item = ToolResultContextItem.from_message(msg, id="t1")
    assert isinstance(item, ToolResultContextItem)
    assert item.id == "t1"
    assert item.role == "tool_result"
    assert item.tool_call_id == msg.tool_call_id
    assert item.tool_name == msg.tool_name
    assert item.details == msg.details
    assert item.is_error is False


# --------------------------------------------------------------------------- #
# to_message
# --------------------------------------------------------------------------- #


def test_to_message_returns_concrete_type_and_drops_id() -> None:
    user_item = UserContextItem.from_message(_user(), id="u1")
    asst_item = AssistantContextItem.from_message(_assistant(), id="a1")
    tool_item = ToolResultContextItem.from_message(_tool_result(), id="t1")

    user_msg = user_item.to_message()
    asst_msg = asst_item.to_message()
    tool_msg = tool_item.to_message()

    assert isinstance(user_msg, UserMessage)
    assert isinstance(asst_msg, AssistantMessage)
    assert isinstance(tool_msg, ToolResultMessage)

    # The message types have no ``id`` field — wrapping was dropped.
    for msg in (user_msg, asst_msg, tool_msg):
        assert "id" not in type(msg).model_fields


def test_to_message_equals_original_message() -> None:
    user_msg = _user()
    asst_msg = _assistant()
    tool_msg = _tool_result()

    assert UserContextItem.from_message(user_msg, id="u1").to_message() == user_msg
    assert AssistantContextItem.from_message(asst_msg, id="a1").to_message() == asst_msg
    assert (
        ToolResultContextItem.from_message(tool_msg, id="t1").to_message() == tool_msg
    )


def test_to_message_from_message_are_inverses() -> None:
    for msg in (_user(), _assistant(), _tool_result()):
        item = context_item(message=msg, id="x")
        assert item.to_message() == msg


# --------------------------------------------------------------------------- #
# context_item() dispatcher
# --------------------------------------------------------------------------- #


def test_context_item_dispatches_by_role() -> None:
    assert isinstance(context_item(message=_user(), id="u1"), UserContextItem)
    assert isinstance(context_item(message=_assistant(), id="a1"), AssistantContextItem)
    assert isinstance(
        context_item(message=_tool_result(), id="t1"), ToolResultContextItem
    )


def test_context_item_preserves_message() -> None:
    for msg in (_user(), _assistant(), _tool_result()):
        assert context_item(message=msg, id="x").to_message() == msg

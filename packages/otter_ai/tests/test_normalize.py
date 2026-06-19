"""Opt-in normalize utilities (drop unreplayable turns; fill missing tool results)."""

from __future__ import annotations

from otter_ai import (
    AssistantMessage,
    Message,
    TextContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserMessage,
    drop_unreplayable_assistant_turns,
    fill_missing_tool_results,
    normalize_messages,
)


def _usage() -> Usage:
    return Usage(
        input=1,
        output=1,
        cache_read=0,
        cache_write=0,
        total_tokens=2,
        cost=UsageCost(input=0, output=0, cache_read=0, cache_write=0, total=0),
    )


def _assistant(
    *,
    tool_calls: list[ToolCall] | None = None,
    stop_reason: str = "stop",
    timestamp: int = 1000,
) -> AssistantMessage:
    content: list[TextContent | ToolCall] = [TextContent(type="text", text="ok")]
    if tool_calls:
        content.extend(tool_calls)
    return AssistantMessage(
        role="assistant",
        content=content,
        api="anthropic-messages",
        provider="anthropic",
        model="claude-3",
        usage=_usage(),
        stop_reason=stop_reason,
        timestamp=timestamp,
    )


def _tool_call(id_: str = "t1", name: str = "get_time") -> ToolCall:
    return ToolCall(type="tool_call", id=id_, name=name, arguments={})


def _tool_result(id_: str = "t1", *, is_error: bool = False) -> ToolResultMessage:
    return ToolResultMessage(
        role="tool_result",
        tool_call_id=id_,
        tool_name="get_time",
        content=[TextContent(type="text", text="r")],
        is_error=is_error,
        timestamp=2000,
    )


def _user() -> UserMessage:
    return UserMessage(role="user", content="go", timestamp=3000)


# --------------------------------------------------------------------------- #
# drop_unreplayable_assistant_turns
# --------------------------------------------------------------------------- #


def test_drops_error_and_aborted_turns() -> None:
    messages: list[Message] = [
        _assistant(stop_reason="error"),
        _user(),
        _assistant(stop_reason="aborted"),
        _assistant(stop_reason="stop"),
    ]
    result = drop_unreplayable_assistant_turns(messages)
    assert result == [messages[1], messages[3]]


def test_keeps_normal_turns() -> None:
    messages: list[Message] = [
        _assistant(stop_reason="stop"),
        _assistant(stop_reason="tool_use"),
        _assistant(stop_reason="length"),
    ]
    assert drop_unreplayable_assistant_turns(messages) == messages


# --------------------------------------------------------------------------- #
# fill_missing_tool_results
# --------------------------------------------------------------------------- #


def test_synthesizes_for_trailing_orphaned_tool_call() -> None:
    messages: list[Message] = [_assistant(tool_calls=[_tool_call()])]
    result = fill_missing_tool_results(messages)
    assert len(result) == 2
    assert isinstance(result[1], ToolResultMessage)
    assert result[1].is_error is True
    assert result[1].tool_call_id == "t1"
    assert isinstance(result[1].content[0], TextContent)
    assert result[1].content[0].text == "No result provided"


def test_does_not_duplicate_existing_result() -> None:
    messages: list[Message] = [
        _assistant(tool_calls=[_tool_call()]),
        _tool_result("t1"),
    ]
    result = fill_missing_tool_results(messages)
    assert result == messages


def test_synthesizes_only_for_missing_ids() -> None:
    # Two tool calls, only one resolved -> one synthetic result for the other.
    messages: list[Message] = [
        _assistant(tool_calls=[_tool_call("t1"), _tool_call("t2", "other")]),
        _tool_result("t1"),
    ]
    result = fill_missing_tool_results(messages)
    assert len(result) == 3
    synthetic = result[2]
    assert isinstance(synthetic, ToolResultMessage)
    assert synthetic.tool_call_id == "t2"
    assert synthetic.is_error is True


def test_synthesizes_across_multiple_turns() -> None:
    # An unresolved call in turn 1 must be closed out before turn 2 starts.
    messages: list[Message] = [
        _assistant(tool_calls=[_tool_call("t1")], timestamp=1000),
        _assistant(tool_calls=[_tool_call("t2")], timestamp=1100),
    ]
    result = fill_missing_tool_results(messages)
    # Expect: asst1, synthetic(t1), asst2, synthetic(t2)
    assert len(result) == 4
    assert isinstance(result[1], ToolResultMessage) and result[1].tool_call_id == "t1"
    assert isinstance(result[3], ToolResultMessage) and result[3].tool_call_id == "t2"


def test_user_message_closes_pending_calls() -> None:
    messages: list[Message] = [
        _assistant(tool_calls=[_tool_call("t1")]),
        _user(),
    ]
    result = fill_missing_tool_results(messages)
    # Expect: asst, synthetic(t1), user
    assert len(result) == 3
    assert isinstance(result[1], ToolResultMessage) and result[1].tool_call_id == "t1"
    assert isinstance(result[2], UserMessage)


def test_does_not_touch_normal_tool_loop() -> None:
    # A complete tool loop (call -> result) must be left untouched.
    messages: list[Message] = [
        _assistant(tool_calls=[_tool_call("t1")]),
        _tool_result("t1"),
        _assistant(),
    ]
    assert fill_missing_tool_results(messages) == messages


def test_does_not_mutate_input() -> None:
    messages: list[Message] = [_assistant(tool_calls=[_tool_call()])]
    original_len = len(messages)
    fill_missing_tool_results(messages)
    assert len(messages) == original_len


# --------------------------------------------------------------------------- #
# normalize_messages
# --------------------------------------------------------------------------- #


def test_normalize_drops_then_fills() -> None:
    messages: list[Message] = [
        _assistant(stop_reason="error", tool_calls=[_tool_call("t9")]),
        _assistant(tool_calls=[_tool_call("t1")]),
    ]
    result = normalize_messages(messages)
    # The errored turn (with its t9 call) is dropped entirely first; then a
    # synthetic result is added for the surviving t1 call.
    assert all(
        not (isinstance(m, AssistantMessage) and m.stop_reason == "error")
        for m in result
    )
    assert len(result) == 2
    assert isinstance(result[1], ToolResultMessage)
    assert result[1].tool_call_id == "t1"


def test_normalize_output_round_trips() -> None:
    from otter_ai import Context

    messages: list[Message] = [
        _assistant(tool_calls=[_tool_call("t1")]),
    ]
    normalized = normalize_messages(messages)
    ctx = Context(messages=normalized)
    restored = Context.model_validate_json(ctx.model_dump_json())
    assert restored.messages == normalized

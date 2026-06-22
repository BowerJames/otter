"""Streaming events: routing, narrowing, ``extra="forbid"``, and round-trip."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from otter_ai import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    AssistantMessageEvent,
    AssistantStartEvent,
    AssistantTextDeltaEvent,
    AssistantTextEndEvent,
    AssistantTextStartEvent,
    AssistantThinkingDeltaEvent,
    AssistantThinkingEndEvent,
    AssistantThinkingStartEvent,
    AssistantToolCallDeltaEvent,
    AssistantToolCallEndEvent,
    AssistantToolCallStartEvent,
    Context,
    ContextItemEvent,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultDoneEvent,
    ToolResultErrorEvent,
    ToolResultMessage,
    ToolResultMessageEvent,
    ToolResultStartEvent,
    ToolResultTextDeltaEvent,
    ToolResultTextEndEvent,
    ToolResultTextStartEvent,
    Usage,
    UsageCost,
    UserDoneEvent,
    UserErrorEvent,
    UserMessage,
    UserMessageEvent,
    UserStartEvent,
    UserTextDeltaEvent,
    UserTextEndEvent,
    UserTextStartEvent,
)

_ASSISTANT_ADAPTER: TypeAdapter[AssistantMessageEvent] = TypeAdapter(
    AssistantMessageEvent
)
_USER_ADAPTER: TypeAdapter[UserMessageEvent] = TypeAdapter(UserMessageEvent)
_TOOL_RESULT_ADAPTER: TypeAdapter[ToolResultMessageEvent] = TypeAdapter(
    ToolResultMessageEvent
)
_CONTEXT_ITEM_ADAPTER: TypeAdapter[ContextItemEvent] = TypeAdapter(ContextItemEvent)


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


def _assistant_partial(**overrides: Any) -> dict[str, Any]:
    """Minimal assistant message dict usable as ``partial``/``message``/``error``."""
    base = {
        "role": "assistant",
        "content": [TextContent(type="text", text="hi").model_dump()],
        "api": "anthropic-messages",
        "provider": "anthropic",
        "model": "claude-3",
        "usage": _usage().model_dump(),
        "stop_reason": "stop",
        "timestamp": 1,
    }
    base.update(overrides)
    return base


def _user_partial(**overrides: Any) -> dict[str, Any]:
    base = {
        "role": "user",
        "content": [TextContent(type="text", text="hi").model_dump()],
        "timestamp": 1,
    }
    base.update(overrides)
    return base


def _tool_result_partial(**overrides: Any) -> dict[str, Any]:
    base = {
        "role": "tool_result",
        "tool_call_id": "t1",
        "tool_name": "get_time",
        "content": [TextContent(type="text", text="12:00").model_dump()],
        "is_error": False,
        "timestamp": 2,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Assistant leaf routing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "typ, leaf",
    [
        ("start", AssistantStartEvent),
        ("text_start", AssistantTextStartEvent),
        ("text_delta", AssistantTextDeltaEvent),
        ("text_end", AssistantTextEndEvent),
        ("thinking_start", AssistantThinkingStartEvent),
        ("thinking_delta", AssistantThinkingDeltaEvent),
        ("thinking_end", AssistantThinkingEndEvent),
        ("tool_call_start", AssistantToolCallStartEvent),
        ("tool_call_delta", AssistantToolCallDeltaEvent),
        ("tool_call_end", AssistantToolCallEndEvent),
        ("done", AssistantDoneEvent),
        ("error", AssistantErrorEvent),
    ],
)
def test_assistant_event_routing(typ: str, leaf: type) -> None:
    payload: dict[str, Any] = {"role": "assistant", "type": typ}
    if typ in {
        "text_start",
        "text_delta",
        "text_end",
        "thinking_start",
        "thinking_delta",
        "thinking_end",
        "tool_call_start",
        "tool_call_delta",
        "tool_call_end",
    }:
        payload["content_index"] = 0
        payload["partial"] = _assistant_partial()
        if "delta" in typ:
            payload["delta"] = "x"
        if typ == "text_end" or typ == "thinking_end":
            payload["content"] = "done"
        if typ == "tool_call_end":
            payload["tool_call"] = ToolCall(
                type="tool_call", id="t1", name="get_time", arguments={}
            ).model_dump()
    elif typ == "start":
        payload["partial"] = _assistant_partial()
    elif typ == "done":
        payload["reason"] = "stop"
        payload["message"] = _assistant_partial()
    elif typ == "error":
        payload["reason"] = "error"
        payload["error"] = _assistant_partial(stop_reason="error", error_message="boom")

    assert isinstance(_ASSISTANT_ADAPTER.validate_python(payload), leaf)


def test_assistant_thinking_and_tool_call_blocks_round_trip() -> None:
    """A rich assistant partial with thinking + tool_call content round-trips."""
    rich = {
        "role": "assistant",
        "content": [
            ThinkingContent(type="thinking", thinking="hmm").model_dump(),
            ToolCall(
                type="tool_call", id="t1", name="get_time", arguments={}
            ).model_dump(),
        ],
        "api": "anthropic-messages",
        "provider": "anthropic",
        "model": "claude-3",
        "usage": _usage().model_dump(),
        "stop_reason": "tool_use",
        "timestamp": 1,
    }
    ev = AssistantToolCallEndEvent(
        role="assistant",
        type="tool_call_end",
        content_index=1,
        tool_call=ToolCall(type="tool_call", id="t1", name="get_time", arguments={}),
        partial=__import__("otter_ai").AssistantMessage.model_validate(rich),
    )
    restored = _ASSISTANT_ADAPTER.validate_json(ev.model_dump_json())
    assert isinstance(restored, AssistantToolCallEndEvent)
    assert restored == ev


# --------------------------------------------------------------------------- #
# User leaf routing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "typ, leaf",
    [
        ("start", UserStartEvent),
        ("text_start", UserTextStartEvent),
        ("text_delta", UserTextDeltaEvent),
        ("text_end", UserTextEndEvent),
        ("done", UserDoneEvent),
        ("error", UserErrorEvent),
    ],
)
def test_user_event_routing(typ: str, leaf: type) -> None:
    payload: dict[str, Any] = {"role": "user", "type": typ}
    if typ == "start":
        payload["partial"] = _user_partial()
    elif typ in {"text_start", "text_delta", "text_end"}:
        payload["content_index"] = 0
        payload["partial"] = _user_partial()
        if typ == "text_delta":
            payload["delta"] = "x"
        if typ == "text_end":
            payload["content"] = "done"
    elif typ == "done":
        payload["message"] = _user_partial()
    elif typ == "error":
        payload["reason"] = "aborted"
        payload["error"] = _user_partial()

    assert isinstance(_USER_ADAPTER.validate_python(payload), leaf)


# --------------------------------------------------------------------------- #
# Tool-result leaf routing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "typ, leaf",
    [
        ("start", ToolResultStartEvent),
        ("text_start", ToolResultTextStartEvent),
        ("text_delta", ToolResultTextDeltaEvent),
        ("text_end", ToolResultTextEndEvent),
        ("done", ToolResultDoneEvent),
        ("error", ToolResultErrorEvent),
    ],
)
def test_tool_result_event_routing(typ: str, leaf: type) -> None:
    payload: dict[str, Any] = {"role": "tool_result", "type": typ}
    if typ == "start":
        payload["partial"] = _tool_result_partial()
    elif typ in {"text_start", "text_delta", "text_end"}:
        payload["content_index"] = 0
        payload["partial"] = _tool_result_partial()
        if typ == "text_delta":
            payload["delta"] = "x"
        if typ == "text_end":
            payload["content"] = "done"
    elif typ == "done":
        payload["message"] = _tool_result_partial()
    elif typ == "error":
        payload["reason"] = "error"
        payload["error"] = _tool_result_partial(is_error=True)

    assert isinstance(_TOOL_RESULT_ADAPTER.validate_python(payload), leaf)


# --------------------------------------------------------------------------- #
# ContextItemEvent: cross-family routing and rejection
# --------------------------------------------------------------------------- #


def test_context_item_routes_each_role() -> None:
    asst = _CONTEXT_ITEM_ADAPTER.validate_python(
        {"role": "assistant", "type": "start", "partial": _assistant_partial()}
    )
    user = _CONTEXT_ITEM_ADAPTER.validate_python(
        {"role": "user", "type": "start", "partial": _user_partial()}
    )
    tool = _CONTEXT_ITEM_ADAPTER.validate_python(
        {"role": "tool_result", "type": "start", "partial": _tool_result_partial()}
    )
    assert isinstance(asst, AssistantStartEvent)
    assert isinstance(user, UserStartEvent)
    assert isinstance(tool, ToolResultStartEvent)


def test_context_item_rejects_bad_role() -> None:
    with pytest.raises(ValidationError):
        _CONTEXT_ITEM_ADAPTER.validate_python(
            {"role": "system", "type": "start", "partial": _user_partial()}
        )


def test_context_item_rejects_bad_role_type_combo() -> None:
    # assistant + tool_call_end is well-formed for the assistant family, but a
    # tool_call_end with role=user has no matching leaf.
    with pytest.raises(ValidationError):
        _CONTEXT_ITEM_ADAPTER.validate_python(
            {
                "role": "user",
                "type": "tool_call_end",
                "content_index": 0,
                "tool_call": ToolCall(
                    type="tool_call", id="t1", name="g", arguments={}
                ).model_dump(),
                "partial": _user_partial(),
            }
        )


# --------------------------------------------------------------------------- #
# extra="forbid"
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "payload, leaf",
    [
        (
            {"role": "assistant", "type": "start", "partial": {}, "unexpected": 1},
            "assistant",
        ),
        (
            {"role": "user", "type": "start", "partial": {}, "unexpected": 1},
            "user",
        ),
        (
            {"role": "tool_result", "type": "start", "partial": {}, "unexpected": 1},
            "tool_result",
        ),
    ],
)
def test_extra_fields_forbidden(payload: dict[str, Any], leaf: str) -> None:
    adapters: dict[str, TypeAdapter[Any]] = {
        "assistant": _ASSISTANT_ADAPTER,
        "user": _USER_ADAPTER,
        "tool_result": _TOOL_RESULT_ADAPTER,
        "context_item": _CONTEXT_ITEM_ADAPTER,
    }
    # A bogus partial triggers extra/missing validation before extra-field, so
    # build a real one per role to isolate the "unexpected" field failure.
    partial = {
        "assistant": _assistant_partial(),
        "user": _user_partial(),
        "tool_result": _tool_result_partial(),
    }[leaf]
    payload = {**payload, "partial": partial}
    with pytest.raises(ValidationError):
        adapters[leaf].validate_python(payload)
    with pytest.raises(ValidationError):
        _CONTEXT_ITEM_ADAPTER.validate_python(payload)


# --------------------------------------------------------------------------- #
# Narrowed reason Literals
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("reason", ["stop", "length", "tool_use"])
def test_assistant_done_accepts_valid_reason(reason: str) -> None:
    ev = AssistantDoneEvent.model_validate(
        {
            "role": "assistant",
            "type": "done",
            "reason": reason,
            "message": _assistant_partial(),
        }
    )
    assert ev.reason == reason


@pytest.mark.parametrize("reason", ["error", "aborted"])
def test_assistant_done_rejects_error_reasons(reason: str) -> None:
    with pytest.raises(ValidationError):
        AssistantDoneEvent.model_validate(
            {
                "role": "assistant",
                "type": "done",
                "reason": reason,
                "message": _assistant_partial(),
            }
        )


@pytest.mark.parametrize("reason", ["error", "aborted"])
def test_assistant_error_accepts_valid_reason(reason: str) -> None:
    ev = AssistantErrorEvent.model_validate(
        {
            "role": "assistant",
            "type": "error",
            "reason": reason,
            "error": _assistant_partial(stop_reason=reason, error_message="x"),
        }
    )
    assert ev.reason == reason


@pytest.mark.parametrize("reason", ["stop", "length", "tool_use"])
def test_assistant_error_rejects_done_reasons(reason: str) -> None:
    with pytest.raises(ValidationError):
        AssistantErrorEvent.model_validate(
            {
                "role": "assistant",
                "type": "error",
                "reason": reason,
                "error": _assistant_partial(),
            }
        )


@pytest.mark.parametrize("reason", ["error", "aborted"])
def test_user_and_tool_result_error_reasons(reason: str) -> None:
    ue = UserErrorEvent.model_validate(
        {"role": "user", "type": "error", "reason": reason, "error": _user_partial()}
    )
    assert ue.reason == reason
    te = ToolResultErrorEvent.model_validate(
        {
            "role": "tool_result",
            "type": "error",
            "reason": reason,
            "error": _tool_result_partial(is_error=True),
        }
    )
    assert te.reason == reason


# --------------------------------------------------------------------------- #
# Terminals reject `partial`; user/tool-result `done` carry no `reason`
# --------------------------------------------------------------------------- #


def test_done_and_error_reject_partial() -> None:
    with pytest.raises(ValidationError):
        AssistantDoneEvent.model_validate(
            {
                "role": "assistant",
                "type": "done",
                "reason": "stop",
                "message": _assistant_partial(),
                "partial": _assistant_partial(),
            }
        )
    with pytest.raises(ValidationError):
        AssistantErrorEvent.model_validate(
            {
                "role": "assistant",
                "type": "error",
                "reason": "error",
                "error": _assistant_partial(),
                "partial": _assistant_partial(),
            }
        )


def test_user_and_tool_result_done_have_no_reason_field() -> None:
    # The literal `type: "done"` models for user/tool_result must not define a
    # `reason` attribute.
    assert "reason" not in UserDoneEvent.model_fields
    assert "reason" not in ToolResultDoneEvent.model_fields
    assert "reason" in AssistantDoneEvent.model_fields


# --------------------------------------------------------------------------- #
# JSON round-trip through the unions
# --------------------------------------------------------------------------- #


def test_assistant_error_round_trip_through_union() -> None:
    import otter_ai

    err = otter_ai.AssistantErrorEvent(
        role="assistant",
        type="error",
        reason="aborted",
        error=otter_ai.AssistantMessage.model_validate(
            _assistant_partial(stop_reason="aborted", error_message="user cancel")
        ),
    )
    restored = _ASSISTANT_ADAPTER.validate_json(err.model_dump_json())
    assert restored == err
    assert _CONTEXT_ITEM_ADAPTER.validate_json(err.model_dump_json()) == err


def test_user_done_round_trip_through_union() -> None:
    ev = UserDoneEvent(
        role="user",
        type="done",
        message=UserMessage.model_validate(_user_partial()),
    )
    restored = _USER_ADAPTER.validate_json(ev.model_dump_json())
    assert restored == ev
    assert _CONTEXT_ITEM_ADAPTER.validate_json(ev.model_dump_json()) == ev


def test_tool_result_done_covers_is_error() -> None:
    """A `done` event may carry a tool result with is_error=True (tool ran, errored)."""
    ev = ToolResultDoneEvent(
        role="tool_result",
        type="done",
        message=ToolResultMessage.model_validate(_tool_result_partial(is_error=True)),
    )
    restored = _TOOL_RESULT_ADAPTER.validate_json(ev.model_dump_json())
    assert restored == ev
    assert restored.message.is_error is True


# --------------------------------------------------------------------------- #
# Consistency: event role literals match the Message role literals
# --------------------------------------------------------------------------- #


def test_event_roles_match_message_roles() -> None:
    from pydantic import BaseModel

    import otter_ai

    # The Literal in each event's `role` must equal the corresponding
    # Message's `role` Literal. Typed against BaseModel so `.model_fields`
    # (a ClassVar) resolves cleanly.
    cases: list[tuple[type[BaseModel], type[BaseModel]]] = [
        (AssistantStartEvent, otter_ai.AssistantMessage),
        (UserStartEvent, otter_ai.UserMessage),
        (ToolResultStartEvent, otter_ai.ToolResultMessage),
        (AssistantDoneEvent, otter_ai.AssistantMessage),
        (UserDoneEvent, otter_ai.UserMessage),
        (ToolResultDoneEvent, otter_ai.ToolResultMessage),
        (AssistantErrorEvent, otter_ai.AssistantMessage),
        (UserErrorEvent, otter_ai.UserMessage),
        (ToolResultErrorEvent, otter_ai.ToolResultMessage),
    ]
    for event_cls, message_cls in cases:
        assert event_cls.model_fields["role"].annotation == (
            message_cls.model_fields["role"].annotation
        )


def test_context_can_hold_messages_built_from_streamed_done_events() -> None:
    """End-to-end: assemble messages from `done` events and persist via Context."""
    asst = AssistantDoneEvent(
        role="assistant",
        type="done",
        reason="tool_use",
        message=__import__("otter_ai").AssistantMessage.model_validate(
            _assistant_partial(stop_reason="tool_use")
        ),
    ).message
    tr = ToolResultDoneEvent(
        role="tool_result",
        type="done",
        message=ToolResultMessage.model_validate(_tool_result_partial()),
    ).message
    ctx = Context(messages=[asst, tr])
    restored = Context.model_validate_json(ctx.model_dump_json())
    assert restored.messages == [asst, tr]

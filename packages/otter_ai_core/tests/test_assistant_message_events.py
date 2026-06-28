"""Streaming events: routing, narrowing, ``extra="forbid"``, and round-trip."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from otter_ai_core import (
    Context,
    TextContent,
    ThinkingContent,
    ToolCall,
    Usage,
    UsageCost,
    context_item,
)
from otter_ai_core.assistant_message_stream import (
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
)

_ASSISTANT_ADAPTER: TypeAdapter[AssistantMessageEvent] = TypeAdapter(
    AssistantMessageEvent
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
        partial=__import__("otter_ai_core").AssistantMessage.model_validate(rich),
    )
    restored = _ASSISTANT_ADAPTER.validate_json(ev.model_dump_json())
    assert isinstance(restored, AssistantToolCallEndEvent)
    assert restored == ev


# --------------------------------------------------------------------------- #
# extra="forbid"
# --------------------------------------------------------------------------- #


def test_extra_fields_forbidden() -> None:
    payload = {
        "role": "assistant",
        "type": "start",
        "partial": _assistant_partial(),
        "unexpected": 1,
    }
    with pytest.raises(ValidationError):
        _ASSISTANT_ADAPTER.validate_python(payload)


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


# --------------------------------------------------------------------------- #
# Terminals reject `partial`; assistant `done` carries `reason`
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


def test_assistant_done_has_reason_field() -> None:
    assert "reason" in AssistantDoneEvent.model_fields


# --------------------------------------------------------------------------- #
# JSON round-trip through the union
# --------------------------------------------------------------------------- #


def test_assistant_error_round_trip_through_union() -> None:
    import otter_ai_core
    from otter_ai_core.assistant_message_stream import AssistantErrorEvent

    err = AssistantErrorEvent(
        role="assistant",
        type="error",
        reason="aborted",
        error=otter_ai_core.AssistantMessage.model_validate(
            _assistant_partial(stop_reason="aborted", error_message="user cancel")
        ),
    )
    restored = _ASSISTANT_ADAPTER.validate_json(err.model_dump_json())
    assert restored == err


# --------------------------------------------------------------------------- #
# Consistency: event role literal matches the Message role literal
# --------------------------------------------------------------------------- #


def test_event_roles_match_message_roles() -> None:
    from pydantic import BaseModel

    import otter_ai_core

    # The Literal in each event's `role` must equal the corresponding
    # Message's `role` Literal. Typed against BaseModel so `.model_fields`
    # (a ClassVar) resolves cleanly.
    cases: list[tuple[type[BaseModel], type[BaseModel]]] = [
        (AssistantStartEvent, otter_ai_core.AssistantMessage),
        (AssistantDoneEvent, otter_ai_core.AssistantMessage),
        (AssistantErrorEvent, otter_ai_core.AssistantMessage),
    ]
    for event_cls, message_cls in cases:
        assert event_cls.model_fields["role"].annotation == (
            message_cls.model_fields["role"].annotation
        )


def test_context_can_hold_messages_built_from_streamed_done_events() -> None:
    """End-to-end: assemble messages from a `done` event and persist via Context."""
    asst = AssistantDoneEvent(
        role="assistant",
        type="done",
        reason="tool_use",
        message=__import__("otter_ai_core").AssistantMessage.model_validate(
            _assistant_partial(stop_reason="tool_use")
        ),
    ).message
    ctx = Context(items=[context_item(message=asst, id="a1")])
    restored = Context.model_validate_json(ctx.model_dump_json())
    assert [i.to_message() for i in restored.items] == [asst]

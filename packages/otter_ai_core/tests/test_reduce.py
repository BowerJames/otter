"""Pure :func:`reduce_server_event`: every raw variant reduces correctly."""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel

from otter_ai_core import (
    AssistantMessage,
    StopReason,
    Usage,
    UsageCost,
    UserMessage,
    context_item,
)
from otter_ai_core.context import Role
from otter_ai_core.model_connection.server_events import (
    ConnectionErrorEvent,
    ContextItemAddedEvent,
    ResponseAbortedEvent,
    ResponseDoneEvent,
    ResponseErrorEvent,
    ResponseStartedEvent,
    ResponseTextDoneEvent,
    ResponseTextStartEvent,
    ResponseTextUpdatedEvent,
    ResponseThinkingDoneEvent,
    ResponseThinkingStartEvent,
    ResponseThinkingUpdateEvent,
    ResponseToolCallDoneEvent,
    ResponseToolCallStartEvent,
    ResponseToolCallUpdateEvent,
    ServerEvent,
    ServerEventTypes,
)
from otter_ai_core.model_session.events import (
    ContextItemAddedEvent as BusContextItemAddedEvent,
)
from otter_ai_core.model_session.events import (
    ResponseAbortedEvent as BusResponseAbortedEvent,
)
from otter_ai_core.model_session.events import (
    ResponseDeltaEvent,
    SessionErrorEvent,
    SessionEvent,
    SessionEventTypes,
)
from otter_ai_core.model_session.events import (
    ResponseDoneEvent as BusResponseDoneEvent,
)
from otter_ai_core.model_session.events import (
    ResponseErrorEvent as BusResponseErrorEvent,
)
from otter_ai_core.model_session.events import (
    ResponseStartedEvent as BusResponseStartedEvent,
)
from otter_ai_core.model_session.reduce import reduce_server_event


def _usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
        cost=UsageCost(
            input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0
        ),
    )


def _assistant_message() -> AssistantMessage:
    return AssistantMessage(
        role=Role.Assistant,
        content=[],
        api="chat-completions",
        provider="openai",
        model="gpt-4o",
        usage=_usage(),
        stop_reason=StopReason.Stop,
        timestamp=0,
    )


def _started() -> ServerEvent:
    return ResponseStartedEvent(
        type=ServerEventTypes.ResponseStarted,
        role=Role.Assistant,
        partial=_assistant_message(),
    )


def _content(kind: str) -> ServerEvent:
    """Build one streaming content event for ``kind``."""
    type_map = {
        "text-start": (ServerEventTypes.ResponseTextContentStarted, "text"),
        "text-update": (ServerEventTypes.ResponseTextContentUpdated, "text"),
        "text-done": (ServerEventTypes.ResponseTextContentDone, "text"),
        "thinking-start": (ServerEventTypes.ResponseThinkingContentStarted, "thinking"),
        "thinking-update": (
            ServerEventTypes.ResponseThinkingContentUpdated,
            "thinking",
        ),
        "thinking-done": (ServerEventTypes.ResponseThinkingContentDone, "thinking"),
        "toolcall-start": (ServerEventTypes.ResponseToolCallStarted, "tool_call"),
        "toolcall-update": (ServerEventTypes.ResponseToolCallUpdated, "tool_call"),
        "toolcall-done": (ServerEventTypes.ResponseToolCallDone, "tool_call"),
    }
    cls_map: dict[str, type[BaseModel]] = {
        "text-start": ResponseTextStartEvent,
        "text-update": ResponseTextUpdatedEvent,
        "text-done": ResponseTextDoneEvent,
        "thinking-start": ResponseThinkingStartEvent,
        "thinking-update": ResponseThinkingUpdateEvent,
        "thinking-done": ResponseThinkingDoneEvent,
        "toolcall-start": ResponseToolCallStartEvent,
        "toolcall-update": ResponseToolCallUpdateEvent,
        "toolcall-done": ResponseToolCallDoneEvent,
    }
    ev_type, content_type = type_map[kind]
    return cast(
        ServerEvent,
        cls_map[kind](
            type=ev_type,
            role=Role.Assistant,
            content_type=content_type,
            content_index=0,
            partial=_assistant_message(),
        ),
    )


def _done() -> ServerEvent:
    return ResponseDoneEvent(
        type=ServerEventTypes.ResponseDone,
        role=Role.Assistant,
        reason="stop",
        partial=_assistant_message(),
    )


def _error() -> ServerEvent:
    return ResponseErrorEvent(
        type=ServerEventTypes.ResponseError,
        role=Role.Assistant,
        reason="error",
        partial=_assistant_message(),
    )


def _aborted() -> ServerEvent:
    return ResponseAbortedEvent(
        type=ServerEventTypes.ResponseAborted,
        role=Role.Assistant,
        reason="aborted",
        partial=_assistant_message(),
    )


def _connection_error() -> ServerEvent:
    return ConnectionErrorEvent(
        type=ServerEventTypes.ConnectionError,
        message="boom",
        reason="transport_error",
    )


def _context_item_added() -> ServerEvent:
    item = context_item(UserMessage(role="user", content="hi", timestamp=0), "u1")
    return ContextItemAddedEvent(
        type=ServerEventTypes.ContextItemAdded,
        item_id="u1",
        role=Role.User,
        item=item,
    )


def test_response_started_reduces_to_response_started() -> None:
    out = list(reduce_server_event(_started()))
    assert len(out) == 1
    assert isinstance(out[0], BusResponseStartedEvent)
    assert out[0].type is SessionEventTypes.ResponseStarted
    assert out[0].partial.stop_reason is StopReason.Stop


def test_every_streaming_content_variant_collapses_to_response_delta() -> None:
    """All 9 content Started/Updated/Done variants reduce to ResponseDelta."""
    variants = [
        "text-start",
        "text-update",
        "text-done",
        "thinking-start",
        "thinking-update",
        "thinking-done",
        "toolcall-start",
        "toolcall-update",
        "toolcall-done",
    ]
    for kind in variants:
        out = list(reduce_server_event(_content(kind)))
        assert len(out) == 1, f"{kind} yielded {len(out)} events"
        assert isinstance(out[0], ResponseDeltaEvent), f"{kind} -> {type(out[0])}"
        assert out[0].type is SessionEventTypes.ResponseDelta


def test_response_done_renames_partial_to_message() -> None:
    out = list(reduce_server_event(_done()))
    assert len(out) == 1
    assert isinstance(out[0], BusResponseDoneEvent)
    assert out[0].type is SessionEventTypes.ResponseDone
    assert out[0].message.stop_reason is StopReason.Stop


def test_response_error_renames_partial_to_message() -> None:
    out = list(reduce_server_event(_error()))
    assert isinstance(out[0], BusResponseErrorEvent)
    assert out[0].type is SessionEventTypes.ResponseError
    # The reduction passes the raw event's ``partial`` straight through as
    # ``message``; it does not rewrite the inner message's stop_reason.
    assert out[0].message.stop_reason is StopReason.Stop


def test_response_aborted_renames_partial_to_message() -> None:
    out = list(reduce_server_event(_aborted()))
    assert isinstance(out[0], BusResponseAbortedEvent)
    assert out[0].type is SessionEventTypes.ResponseAborted
    assert out[0].message.stop_reason is StopReason.Stop


def test_connection_error_reduces_to_session_error() -> None:
    out = list(reduce_server_event(_connection_error()))
    assert isinstance(out[0], SessionErrorEvent)
    assert out[0].type is SessionEventTypes.SessionError
    assert out[0].message == "boom"
    assert out[0].reason == "transport_error"


def test_context_item_added_passes_through_fields() -> None:
    out = list(reduce_server_event(_context_item_added()))
    assert isinstance(out[0], BusContextItemAddedEvent)
    assert out[0].type is SessionEventTypes.ContextItemAdded
    assert out[0].item_id == "u1"
    assert out[0].role is Role.User


def test_every_raw_variant_is_covered() -> None:
    """Guard against a new ServerEvent variant being added without a reduction case."""
    all_raw = [
        _started(),
        *[
            _content(k)
            for k in (
                "text-start",
                "text-update",
                "text-done",
                "thinking-start",
                "thinking-update",
                "thinking-done",
                "toolcall-start",
                "toolcall-update",
                "toolcall-done",
            )
        ],
        _done(),
        _error(),
        _aborted(),
        _connection_error(),
        _context_item_added(),
    ]
    for raw in all_raw:
        out = list(reduce_server_event(raw))
        assert len(out) == 1, f"{raw.type} yielded {len(out)}"
        # Each output is a member of the SessionEvent union.
        assert isinstance(out[0], SessionEvent.__args__)


def test_output_yields_at_most_one_per_input_today() -> None:
    """Documents the 1:1 contract; pins behavior if a synthesis case is added later."""
    out = list(reduce_server_event(_done()))
    assert len(out) == 1

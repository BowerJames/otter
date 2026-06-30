"""Translation table: every ``AssistantMessageEvent`` → ``ServerEvent`` mapping."""

from __future__ import annotations

import uuid

from _adapter_helpers import (
    done_event,
    error_event,
    make_message,
    simple_context,
    start_event,
    text_block,
    text_delta,
    text_end,
    text_start,
    thinking_block,
    thinking_delta,
    thinking_end,
    thinking_start,
    tool_call,
    tool_call_delta,
    tool_call_end,
    tool_call_start,
)

from otter_ai_assistant_stream_model_connection._translate import translate
from otter_ai_core import Context
from otter_ai_core.context import ContentType, StopReason
from otter_ai_core.model_connection import (
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
)


def _ctx() -> Context:
    return simple_context()


def test_start_maps_to_response_started() -> None:
    partial = make_message()
    [event] = translate(start_event(partial), _ctx())
    assert isinstance(event, ResponseStartedEvent)
    assert event.partial is partial


def test_text_lifecycle_maps_dropping_delta_and_content() -> None:
    partial = make_message(content=[text_block("")])
    starts = translate(text_start(0, partial), _ctx())
    d1 = translate(text_delta(0, "Hi ", partial), _ctx())
    d2 = translate(text_delta(0, "there", partial), _ctx())
    ends = translate(text_end(0, "Hi there", partial), _ctx())

    assert isinstance(starts[0], ResponseTextStartEvent)
    assert isinstance(d1[0], ResponseTextUpdatedEvent)
    assert isinstance(d2[0], ResponseTextUpdatedEvent)
    assert isinstance(ends[0], ResponseTextDoneEvent)
    for group in (starts, d1, d2, ends):
        first = group[0]
        assert isinstance(
            first,
            (ResponseTextStartEvent, ResponseTextUpdatedEvent, ResponseTextDoneEvent),
        )
        assert first.content_type == ContentType.Text
        assert first.content_index == 0
        assert first.partial is partial


def test_thinking_lifecycle_maps() -> None:
    partial = make_message(content=[thinking_block("")])
    starts = translate(thinking_start(0, partial), _ctx())
    upd = translate(thinking_delta(0, "hmm", partial), _ctx())
    ends = translate(thinking_end(0, "hmm", partial), _ctx())

    assert isinstance(starts[0], ResponseThinkingStartEvent)
    assert isinstance(upd[0], ResponseThinkingUpdateEvent)
    assert isinstance(ends[0], ResponseThinkingDoneEvent)
    for group in (starts, upd, ends):
        first = group[0]
        assert isinstance(
            first,
            (
                ResponseThinkingStartEvent,
                ResponseThinkingUpdateEvent,
                ResponseThinkingDoneEvent,
            ),
        )
        assert first.content_type == ContentType.Thinking


def test_tool_call_lifecycle_maps() -> None:
    call = tool_call(arguments={"x": 1})
    partial = make_message(content=[call])
    starts = translate(tool_call_start(0, partial), _ctx())
    upd = translate(tool_call_delta(0, '{"x":1}', partial), _ctx())
    ends = translate(tool_call_end(0, call, partial), _ctx())

    assert isinstance(starts[0], ResponseToolCallStartEvent)
    assert isinstance(upd[0], ResponseToolCallUpdateEvent)
    assert isinstance(ends[0], ResponseToolCallDoneEvent)
    for group in (starts, upd, ends):
        first = group[0]
        assert isinstance(
            first,
            (
                ResponseToolCallStartEvent,
                ResponseToolCallUpdateEvent,
                ResponseToolCallDoneEvent,
            ),
        )
        assert first.content_type == ContentType.ToolCall


def test_done_emits_done_plus_auto_append_with_uuid() -> None:
    ctx = _ctx()
    message = make_message(content=[text_block("Hi")])
    out: list[ServerEvent] = translate(done_event(message), ctx)

    # Two events: ResponseDoneEvent then ContextItemAddedEvent.
    assert len(out) == 2
    assert isinstance(out[0], ResponseDoneEvent)
    assert out[0].partial is message
    assert out[0].reason == StopReason.Stop

    assert isinstance(out[1], ContextItemAddedEvent)
    # The auto-appended assistant item carries a fresh uuid4 id.
    assert _is_uuid4(out[1].item_id)
    assert out[1].role == "assistant"

    # The context was mutated: the message is now the first item.
    assert len(ctx.items) == 1
    assert ctx.items[0].to_message() == message


def test_done_with_tool_use_reason_passes_through() -> None:
    message = make_message(content=[tool_call()], stop_reason="tool_use")
    out = translate(done_event(message, reason="tool_use"), _ctx())
    # ``done`` always emits ResponseDoneEvent + auto-append ContextItemAddedEvent.
    assert isinstance(out[0], ResponseDoneEvent)
    assert out[0].reason == StopReason.ToolUse


def test_error_routes_to_response_error() -> None:
    partial = make_message(stop_reason="error", error_message="boom")
    [event] = translate(error_event(partial, reason="error"), _ctx())
    assert isinstance(event, ResponseErrorEvent)
    assert event.reason == StopReason.Error
    assert event.partial is partial


def test_aborted_routes_to_response_aborted_and_does_not_append() -> None:
    ctx = _ctx()
    partial = make_message(stop_reason="aborted")
    [event] = translate(error_event(partial, reason="aborted"), ctx)
    assert isinstance(event, ResponseAbortedEvent)
    assert event.reason == StopReason.Aborted
    # Aborted responses are unreplayable — never appended.
    assert ctx.items == []


def _is_uuid4(value: str) -> bool:
    try:
        return uuid.UUID(value).version == 4
    except (ValueError, TypeError):
        return False

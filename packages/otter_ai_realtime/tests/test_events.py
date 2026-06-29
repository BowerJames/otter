"""Tests for the bidirectional Realtime ↔ otter event translation."""

from __future__ import annotations

from _realtime_helpers import (
    content_part_added,
    error_frame,
    fc_args_delta,
    fc_args_done,
    fc_item_added,
    make_model,
    output_item_done,
    response_cancelled,
    response_completed,
    response_created,
    text_frame_delta,
    text_frame_done,
    user_text,
)

from otter_ai_core import (
    StopReason,
    TextContent,
    ToolCall,
    ToolResultMessage,
    context_item,
)
from otter_ai_core.context import Role
from otter_ai_core.model_connection import (
    AbortResponseEvent,
    ContextItemAddedEvent,
    ContextItemAddEvent,
    ResponseAbortedEvent,
    ResponseCreate,
    ResponseDoneEvent,
    ResponseErrorEvent,
    ResponseTextUpdatedEvent,
    ResponseToolCallDoneEvent,
    ServerEventTypes,
)
from otter_ai_realtime._events import (
    InboundTranslator,
    client_event_to_frame,
    connection_error,
)


def _translator() -> InboundTranslator:
    return InboundTranslator(make_model())


def test_text_response_lifecycle() -> None:
    t = _translator()
    events = []
    events += t.feed(response_created())
    events += t.feed(content_part_added())
    events += t.feed(text_frame_delta("Hel"))
    events += t.feed(text_frame_delta("lo"))
    events += t.feed(text_frame_done("Hello"))
    events += t.feed(response_completed())

    types = [type(e).__name__ for e in events]
    assert types == [
        "ResponseStartedEvent",
        "ResponseTextStartEvent",
        "ResponseTextUpdatedEvent",
        "ResponseTextUpdatedEvent",
        "ResponseTextDoneEvent",
        "ResponseDoneEvent",
    ]
    done = events[-1]
    assert isinstance(done, ResponseDoneEvent)
    assert done.reason == StopReason.Stop
    text_block = done.partial.content[0]
    assert isinstance(text_block, TextContent)
    assert text_block.text == "Hello"
    assert done.partial.response_id == "resp_1"


def test_text_delta_without_part_added_opens_block() -> None:
    t = _translator()
    t.feed(response_created())
    # content_part.added missing — delta should still open a text block.
    [update] = t.feed(text_frame_delta("hi"))
    assert isinstance(update, ResponseTextUpdatedEvent)
    block = update.partial.content[0]
    assert isinstance(block, TextContent)
    assert block.text == "hi"


def test_tool_call_response_marks_tool_use_stop_reason() -> None:
    t = _translator()
    events = []
    events += t.feed(response_created())
    events += t.feed(fc_item_added("call_9", "get_weather"))
    events += t.feed(fc_args_delta('{"city":"'))
    events += t.feed(fc_args_delta('SF"}'))
    events += t.feed(fc_args_done("call_9", "get_weather", '{"city":"SF"}'))
    events += t.feed(response_completed())

    types = [type(e).__name__ for e in events]
    assert types == [
        "ResponseStartedEvent",
        "ResponseToolCallStartEvent",
        "ResponseToolCallUpdateEvent",
        "ResponseToolCallUpdateEvent",
        "ResponseToolCallDoneEvent",
        "ResponseDoneEvent",
    ]
    done = events[-1]
    assert isinstance(done, ResponseDoneEvent)
    assert done.reason == StopReason.ToolUse
    tc = done.partial.content[0]
    assert isinstance(tc, ToolCall)
    assert tc.name == "get_weather"
    assert tc.arguments == {"city": "SF"}


def test_tool_call_done_not_emitted_twice_for_args_done_then_output_item_done() -> None:
    """The Realtime API fires BOTH function_call_arguments.done AND
    output_item.done for a function call — the done event must fire once."""
    t = _translator()
    events = []
    events += t.feed(response_created())
    events += t.feed(fc_item_added("call_9", "get_weather"))
    events += t.feed(fc_args_delta('{"city":"'))
    events += t.feed(fc_args_done("call_9", "get_weather", '{"city":"SF"}'))
    # The Realtime API then re-states the same item via output_item.done.
    events += t.feed(output_item_done("call_9", "get_weather", '{"city":"SF"}'))
    events += t.feed(response_completed())

    done_events = [e for e in events if isinstance(e, ResponseToolCallDoneEvent)]
    assert len(done_events) == 1


def test_mixed_text_and_tool_call_in_one_response() -> None:
    """A response with text content followed by a tool call (the common case
    where the model explains, then acts)."""
    t = _translator()
    events = []
    events += t.feed(response_created())
    events += t.feed(content_part_added())
    events += t.feed(text_frame_delta("Let me check "))
    events += t.feed(text_frame_done("Let me check "))
    events += t.feed(fc_item_added("call_1", "get_weather"))
    events += t.feed(fc_args_delta('{"city":"SF"}'))
    events += t.feed(fc_args_done("call_1", "get_weather", '{"city":"SF"}'))
    events += t.feed(output_item_done("call_1", "get_weather", '{"city":"SF"}'))
    events += t.feed(response_completed())

    types = [type(e).__name__ for e in events]
    assert types == [
        "ResponseStartedEvent",
        "ResponseTextStartEvent",
        "ResponseTextUpdatedEvent",
        "ResponseTextDoneEvent",
        "ResponseToolCallStartEvent",
        "ResponseToolCallUpdateEvent",
        "ResponseToolCallDoneEvent",
        "ResponseDoneEvent",
    ]
    done = events[-1]
    assert isinstance(done, ResponseDoneEvent)
    assert done.reason == StopReason.ToolUse
    text_block = done.partial.content[0]
    assert isinstance(text_block, TextContent)
    assert text_block.text == "Let me check "
    tc = done.partial.content[1]
    assert isinstance(tc, ToolCall)
    assert tc.arguments == {"city": "SF"}
    # And only one tool-call done despite args.done + output_item.done.
    assert sum(1 for e in events if isinstance(e, ResponseToolCallDoneEvent)) == 1


def test_response_cancelled_emits_aborted_event() -> None:
    t = _translator()
    t.feed(response_created())
    [event] = t.feed(response_cancelled())
    assert isinstance(event, ResponseAbortedEvent)
    assert event.reason == StopReason.Aborted


def test_error_frame_emits_response_error() -> None:
    t = _translator()
    t.feed(response_created())
    [event] = t.feed(error_frame("kaboom"))
    assert isinstance(event, ResponseErrorEvent)
    assert event.reason == StopReason.Error
    assert event.partial.error_message == "kaboom"


def test_error_outside_response_still_emits_error() -> None:
    t = _translator()
    [event] = t.feed(error_frame("nope"))
    assert isinstance(event, ResponseErrorEvent)
    assert event.partial.error_message == "nope"


def test_conversation_item_created_user_message() -> None:
    t = _translator()
    frame = {
        "type": "conversation.item.created",
        "item": {
            "id": "msg_1",
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "hi"}],
        },
    }
    [event] = t.feed(frame)
    assert isinstance(event, ContextItemAddedEvent)
    assert event.item_id == "msg_1"
    assert event.role == Role.User
    assert event.item.role == Role.User


def test_conversation_item_created_function_call() -> None:
    t = _translator()
    frame = {
        "type": "conversation.item.created",
        "item": {
            "id": "fc_1",
            "type": "function_call",
            "call_id": "call_1",
            "name": "get_weather",
            "arguments": '{"city":"SF"}',
        },
    }
    [event] = t.feed(frame)
    assert isinstance(event, ContextItemAddedEvent)
    assert event.item_id == "fc_1"
    assert event.item.role == "assistant"
    msg = event.item.to_message()
    tc = msg.content[0]
    assert isinstance(tc, ToolCall)
    assert tc.id == "call_1"
    assert tc.name == "get_weather"
    assert tc.arguments == {"city": "SF"}


def test_conversation_item_created_function_call_output() -> None:
    t = _translator()
    frame = {
        "type": "conversation.item.created",
        "item": {
            "id": "fco_1",
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "sunny",
        },
    }
    [event] = t.feed(frame)
    assert isinstance(event, ContextItemAddedEvent)
    assert event.item_id == "fco_1"
    assert event.item.role == "tool_result"
    msg = event.item.to_message()
    assert isinstance(msg, ToolResultMessage)
    assert msg.tool_call_id == "call_1"
    block = msg.content[0]
    assert isinstance(block, TextContent)
    assert block.text == "sunny"


def test_conversation_item_created_unmapped_type_is_dropped() -> None:
    t = _translator()
    frame = {
        "type": "conversation.item.created",
        "item": {"id": "x", "type": "something_new"},
    }
    assert t.feed(frame) == []


def test_client_event_response_create() -> None:
    assert client_event_to_frame(ResponseCreate(type="response.create")) == {
        "type": "response.create"
    }


def test_client_event_abort_response() -> None:
    assert client_event_to_frame(AbortResponseEvent(type="response.abort")) == {
        "type": "response.cancel"
    }


def test_client_event_context_item_add() -> None:
    item = context_item(message=user_text("hello"), id="u1")
    frame = client_event_to_frame(
        ContextItemAddEvent(type="context_item.add", item=item)
    )
    assert frame["type"] == "conversation.item.create"
    assert frame["item"]["role"] == "user"
    assert frame["item"]["content"] == [{"type": "input_text", "text": "hello"}]


def test_connection_error_event_builder() -> None:
    ev = connection_error("boom", "transport_error")
    assert ev.type == ServerEventTypes.ConnectionError
    assert ev.message == "boom"
    assert ev.reason == "transport_error"


def test_unknown_frame_is_ignored() -> None:
    t = _translator()
    assert t.feed({"type": "totally.unknown"}) == []

"""Behavioural tests for the Chat Completions stream, faking httpx."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from _helpers import (
    collect,
    error_response,
    install_fake_transport,
    make_options,
    simple_context,
    sse_response,
)

from otter_ai import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    AssistantStartEvent,
    AssistantTextDeltaEvent,
    AssistantTextEndEvent,
    AssistantTextStartEvent,
    AssistantThinkingDeltaEvent,
    AssistantThinkingEndEvent,
    AssistantToolCallDeltaEvent,
    AssistantToolCallEndEvent,
    AssistantToolCallStartEvent,
    TextContent,
    ThinkingContent,
    ToolCall,
)
from otter_ai_chat_completions import (
    ChatCompletionsHooks,
    OnPayloadEvent,
    OnResponseEvent,
    create_chat_completions_assistant_message_stream,
)
from otter_ai_chat_completions import stream as stream_module


def _delta_chunk(
    delta: dict[str, Any], finish_reason: str | None = None, **extra: Any
) -> dict[str, Any]:
    choice: dict[str, Any] = {"delta": delta}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    return {"id": "resp_1", "choices": [choice], **extra}


def _usage_chunk(
    usage: dict[str, Any], finish_reason: str | None = None
) -> dict[str, Any]:
    return {
        "id": "resp_1",
        "choices": [{"delta": {}, "finish_reason": finish_reason}],
        "usage": usage,
    }


# --------------------------------------------------------------------------- #
# Happy path: text streaming
# --------------------------------------------------------------------------- #


async def test_text_stream_emits_full_event_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = [
        _delta_chunk({"content": "Hel"}),
        _delta_chunk({"content": "lo"}),
        _delta_chunk({}, finish_reason="stop"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return sse_response(chunks)

    install_fake_transport(monkeypatch, handler)
    stream = create_chat_completions_assistant_message_stream(
        make_options(), simple_context()
    )
    events = await collect(stream)

    assert isinstance(events[0], AssistantStartEvent)
    assert isinstance(events[1], AssistantTextStartEvent)
    deltas = [e for e in events if isinstance(e, AssistantTextDeltaEvent)]
    assert [d.delta for d in deltas] == ["Hel", "lo"]
    assert isinstance(events[-2], AssistantTextEndEvent)
    done = events[-1]
    assert isinstance(done, AssistantDoneEvent)
    assert done.reason == "stop"
    assert any(
        isinstance(b, TextContent) and b.text == "Hello" for b in done.message.content
    )


async def test_response_id_and_response_model_captured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = [
        {
            "id": "resp-abc",
            "model": "gpt-4o-2024",
            "choices": [{"delta": {}, "finish_reason": "stop"}],
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return sse_response(chunks)

    install_fake_transport(monkeypatch, handler)
    # Use a model id that differs from the chunk's so response_model is set.
    options = make_options(
        model=make_options().model.model_copy(update={"id": "gpt-4o"})
    )
    stream = create_chat_completions_assistant_message_stream(options, simple_context())
    events = await collect(stream)
    done = next(e for e in events if isinstance(e, AssistantDoneEvent))
    assert done.message.response_id == "resp-abc"
    assert done.message.response_model == "gpt-4o-2024"


# --------------------------------------------------------------------------- #
# Thinking streaming
# --------------------------------------------------------------------------- #


async def test_thinking_stream_uses_reasoning_content_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = [
        _delta_chunk({"reasoning_content": "thin"}),
        _delta_chunk({"reasoning_content": "king"}),
        _delta_chunk({"content": "answer"}),
        _delta_chunk({}, finish_reason="stop"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return sse_response(chunks)

    install_fake_transport(monkeypatch, handler)
    stream = create_chat_completions_assistant_message_stream(
        make_options(), simple_context()
    )
    events = await collect(stream)

    thinking_deltas = [e for e in events if isinstance(e, AssistantThinkingDeltaEvent)]
    assert [d.delta for d in thinking_deltas] == ["thin", "king"]
    thinking_end = next(e for e in events if isinstance(e, AssistantThinkingEndEvent))
    assert thinking_end.content == "thinking"
    done = next(e for e in events if isinstance(e, AssistantDoneEvent))
    assert any(
        isinstance(b, ThinkingContent) and b.thinking == "thinking"
        for b in done.message.content
    )


async def test_thinking_first_nonempty_field_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # chutes.ai-style: both ``reasoning_content`` and ``reasoning`` present; only
    # the first non-empty one should be emitted.
    chunks = [
        _delta_chunk({"reasoning_content": "a", "reasoning": "b"}),
        _delta_chunk({}, finish_reason="stop"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return sse_response(chunks)

    install_fake_transport(monkeypatch, handler)
    stream = create_chat_completions_assistant_message_stream(
        make_options(), simple_context()
    )
    events = await collect(stream)
    thinking_deltas = [e for e in events if isinstance(e, AssistantThinkingDeltaEvent)]
    assert [d.delta for d in thinking_deltas] == ["a"]


# --------------------------------------------------------------------------- #
# Tool-call streaming
# --------------------------------------------------------------------------- #


async def test_tool_call_stream_finalizes_parsed_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = [
        _delta_chunk(
            {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "add"}}]}
        ),
        _delta_chunk(
            {"tool_calls": [{"index": 0, "function": {"arguments": '{"x":'}}]}
        ),
        _delta_chunk({"tool_calls": [{"index": 0, "function": {"arguments": " 1}"}}]}),
        _delta_chunk({}, finish_reason="tool_calls"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return sse_response(chunks)

    install_fake_transport(monkeypatch, handler)
    stream = create_chat_completions_assistant_message_stream(
        make_options(), simple_context()
    )
    events = await collect(stream)

    assert isinstance(events[1], AssistantToolCallStartEvent)
    deltas = [e for e in events if isinstance(e, AssistantToolCallDeltaEvent)]
    assert "".join(d.delta for d in deltas) == '{"x": 1}'
    end = next(e for e in events if isinstance(e, AssistantToolCallEndEvent))
    assert end.tool_call == ToolCall(
        type="tool_call", id="call_1", name="add", arguments={"x": 1}
    )
    done = next(e for e in events if isinstance(e, AssistantDoneEvent))
    assert done.reason == "tool_use"
    assert done.message.content[0] == ToolCall(
        type="tool_call", id="call_1", name="add", arguments={"x": 1}
    )


# --------------------------------------------------------------------------- #
# Usage + finish_reason mapping
# --------------------------------------------------------------------------- #


async def test_usage_parsed_from_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [
        _delta_chunk({"content": "hi"}),
        _usage_chunk(
            {
                "prompt_tokens": 100,
                "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 10},
            },
            finish_reason="stop",
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return sse_response(chunks)

    install_fake_transport(monkeypatch, handler)
    stream = create_chat_completions_assistant_message_stream(
        make_options(), simple_context()
    )
    events = await collect(stream)
    done = next(e for e in events if isinstance(e, AssistantDoneEvent))
    assert done.message.usage.input == 90  # 100 - 10 cache_read
    assert done.message.usage.cache_read == 10
    assert done.message.usage.output == 5


async def test_usage_fallback_on_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    # Some providers (e.g. Moonshot) place usage on the choice, not the chunk.
    chunks = [
        {
            "id": "r",
            "choices": [
                {
                    "delta": {},
                    "finish_reason": "stop",
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                },
            ],
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return sse_response(chunks)

    install_fake_transport(monkeypatch, handler)
    stream = create_chat_completions_assistant_message_stream(
        make_options(), simple_context()
    )
    events = await collect(stream)
    done = next(e for e in events if isinstance(e, AssistantDoneEvent))
    assert done.message.usage.input == 7
    assert done.message.usage.output == 3


async def test_length_finish_reason_mapped(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [_delta_chunk({}, finish_reason="length")]

    def handler(request: httpx.Request) -> httpx.Response:
        return sse_response(chunks)

    install_fake_transport(monkeypatch, handler)
    stream = create_chat_completions_assistant_message_stream(
        make_options(), simple_context()
    )
    events = await collect(stream)
    done = next(e for e in events if isinstance(e, AssistantDoneEvent))
    assert done.reason == "length"


# --------------------------------------------------------------------------- #
# Error + abort paths (the seam never raises)
# --------------------------------------------------------------------------- #


async def test_missing_api_key_emits_error_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_transport(monkeypatch, lambda request: sse_response([]))
    options = make_options(
        model=make_options().model.model_copy(update={"api_key": None})
    )
    stream = create_chat_completions_assistant_message_stream(options, simple_context())
    events = await collect(stream)
    err = events[-1]
    assert isinstance(err, AssistantErrorEvent)
    assert err.reason == "error"
    assert "No API key" in (err.error.error_message or "")


async def test_http_error_status_emits_error_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return error_response(500, "server boom")

    install_fake_transport(monkeypatch, handler)
    stream = create_chat_completions_assistant_message_stream(
        make_options(), simple_context()
    )
    events = await collect(stream)
    err = events[-1]
    assert isinstance(err, AssistantErrorEvent)
    assert "500" in (err.error.error_message or "")
    assert "server boom" in (err.error.error_message or "")


async def test_abort_emits_aborted_error_event(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pre-setting the abort signal exercises the per-chunk / pre-send abort
    # check: the producer must emit an ``AssistantErrorEvent`` with
    # ``reason="aborted"`` and never raise. (Partial content is preserved
    # structurally — content is appended to ``output`` which is carried on the
    # error event — but we cannot deterministically trigger mid-stream abort
    # with ``MockTransport`` since it buffers the whole body at once.)
    def handler(request: httpx.Request) -> httpx.Response:
        return sse_response([_delta_chunk({"content": "x"}, finish_reason="stop")])

    install_fake_transport(monkeypatch, handler)
    options = make_options()
    options.abort_signal.set()
    stream = create_chat_completions_assistant_message_stream(options, simple_context())
    events = await collect(stream)
    err = events[-1]
    assert isinstance(err, AssistantErrorEvent)
    assert err.reason == "aborted"
    assert err.error.stop_reason == "aborted"


async def test_no_finish_reason_emits_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Stream ends via [DONE] with no finish_reason anywhere.
    chunks = [_delta_chunk({"content": "x"})]

    def handler(request: httpx.Request) -> httpx.Response:
        return sse_response(chunks)

    install_fake_transport(monkeypatch, handler)
    stream = create_chat_completions_assistant_message_stream(
        make_options(), simple_context()
    )
    events = await collect(stream)
    err = events[-1]
    assert isinstance(err, AssistantErrorEvent)
    assert "without finish_reason" in (err.error.error_message or "")


# --------------------------------------------------------------------------- #
# Hooks
# --------------------------------------------------------------------------- #


async def test_on_payload_can_replace_body(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return sse_response([_delta_chunk({}, finish_reason="stop")])

    install_fake_transport(monkeypatch, handler)

    async def on_payload(event: OnPayloadEvent) -> dict[str, Any]:
        new_body = dict(event.payload)
        new_body["injected"] = True
        return new_body

    options = make_options(hooks=ChatCompletionsHooks(on_payload=on_payload))
    stream = create_chat_completions_assistant_message_stream(options, simple_context())
    await collect(stream)
    assert captured["body"].get("injected") is True


async def test_on_response_observed(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return sse_response([_delta_chunk({}, finish_reason="stop")])

    install_fake_transport(monkeypatch, handler)

    async def on_response(event: OnResponseEvent) -> None:
        seen["status"] = event.status

    options = make_options(hooks=ChatCompletionsHooks(on_response=on_response))
    stream = create_chat_completions_assistant_message_stream(options, simple_context())
    await collect(stream)
    assert seen["status"] == 200


# --------------------------------------------------------------------------- #
# Retry
# --------------------------------------------------------------------------- #


async def test_retry_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            resp = error_response(429, "slow down")
            resp.headers["Retry-After"] = "0"  # zero delay so the test is fast
            return resp
        return sse_response([_delta_chunk({}, finish_reason="stop")])

    install_fake_transport(monkeypatch, handler)
    options = make_options(
        model=make_options().model.model_copy(update={"max_retries": 2})
    )
    stream = create_chat_completions_assistant_message_stream(options, simple_context())
    events = await collect(stream)
    assert calls["n"] == 2
    assert isinstance(events[-1], AssistantDoneEvent)


async def test_retry_after_exceeding_cap_fails_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        resp = error_response(429, "slow down")
        resp.headers["Retry-After"] = "3600"  # 1h, well over the 60s cap
        return resp

    install_fake_transport(monkeypatch, handler)
    options = make_options(
        model=make_options().model.model_copy(update={"max_retries": 3})
    )
    stream = create_chat_completions_assistant_message_stream(options, simple_context())
    events = await collect(stream)
    err = events[-1]
    assert isinstance(err, AssistantErrorEvent)
    assert "exceeding cap" in (err.error.error_message or "")


# --------------------------------------------------------------------------- #
# Strong-ref invariant
# --------------------------------------------------------------------------- #


async def test_producer_task_tracked_during_run_and_discarded_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The producer task is held in ``_producer_tasks`` to prevent asyncio
    # GC-cancelling it; after the producer completes the done-callback
    # discards it. We assert the set is empty after a full run.
    def handler(request: httpx.Request) -> httpx.Response:
        return sse_response([_delta_chunk({}, finish_reason="stop")])

    install_fake_transport(monkeypatch, handler)

    stream = create_chat_completions_assistant_message_stream(
        make_options(), simple_context()
    )
    await collect(stream)
    # Give the done callback a beat to run.
    for _ in range(10):
        await asyncio.sleep(0)
    assert stream_module._producer_tasks == set()

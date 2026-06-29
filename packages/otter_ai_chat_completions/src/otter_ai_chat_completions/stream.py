"""The Chat Completions ``AssistantMessageStreamFnBuilder`` seam.

:func:`create_chat_completions_assistant_message_stream` is a concrete
implementation of
:data:`otter_ai_core.assistant_message_stream.AssistantMessageStreamFnBuilder`
for the Chat Completions wire format. It is a faithful async/:mod:`httpx` port
of pi-ai's ``streamOpenAICompletions``.

The seam is **synchronous**: it returns the
:class:`~otter_ai_core.assistant_message_stream.AssistantMessageStream`
immediately and schedules its producer via :func:`asyncio.create_task`. The
producer pushes every streaming event, including the terminal
``done``/:class:`~otter_ai_core.assistant_message_stream.AssistantErrorEvent`,
then calls ``end()`` on the writer. The seam **never raises** —
request/model/runtime failures are encoded as
:class:`~otter_ai_core.assistant_message_stream.AssistantErrorEvent` (with
``stop_reason`` of ``"error"`` or ``"aborted"`` and ``error_message`` set).

Cooperative abort is honoured via the ``abort`` argument (an
:class:`asyncio.Event`), checked between SSE chunks and around the request
send. On abort the producer emits an
:class:`~otter_ai_core.assistant_message_stream.AssistantErrorEvent` with
``reason="aborted"`` and stops, preserving any partial content.

Hooks (pi-ai parity):

* ``options.hooks.on_payload`` — awaited pre-send with the fully-built request
  body; a non-``None`` return **replaces** the body.
* ``options.hooks.on_response`` — awaited post-headers / pre-body with a narrow
  ``{status, headers}`` view; observer, return ignored.

Retry/timeout (full parity):

* ``options.model.timeout_ms`` → per-request timeout (default 600s).
* ``options.model.max_retries`` → retries on 429/5xx after ``Retry-After``
  (capped by ``options.model.max_retry_delay_ms``, default 60000). A server
  delay over the cap fails immediately so higher-level logic can decide.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Any

import httpx

from otter_ai_chat_completions._compat import resolve_compat
from otter_ai_chat_completions._json import parse_streaming_json
from otter_ai_chat_completions._params import build_params
from otter_ai_chat_completions._sse import iter_sse_events
from otter_ai_chat_completions._usage import map_stop_reason, parse_chunk_usage
from otter_ai_chat_completions.hooks import OnPayloadEvent, OnResponseEvent
from otter_ai_chat_completions.models import ChatCompletionsModel
from otter_ai_chat_completions.options import ChatCompletionsModelOptions
from otter_ai_core import (
    AssistantContent,
    AssistantMessage,
    Context,
    StopReason,
    TextContent,
    ThinkingContent,
    ToolCall,
    Usage,
    UsageCost,
    create_stream,
)
from otter_ai_core.assistant_message_stream import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    AssistantMessageStream,
    AssistantMessageWriter,
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

#: Default request timeout (seconds) when ``model.timeout_ms`` is unset.
#: Matches the OpenAI SDK default (10 minutes).
_DEFAULT_TIMEOUT_SECONDS = 600.0

#: Default cap (seconds) on a server-requested retry delay.
_DEFAULT_MAX_RETRY_DELAY_SECONDS = 60.0

#: HTTP status codes that trigger a retry (transient failures).
_RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

#: Reasoning-bearing delta fields in priority order (first non-empty wins).
_REASONING_FIELDS = ("reasoning_content", "reasoning", "reasoning_text")

#: Strong references to in-flight producer tasks. asyncio will cancel a task
#: with no live reference before it completes; we hold one until the producer
#: finishes. (See the develop-mode plan for :issue:`13`.) The set is valid
#: within a single event loop: each ``create_task`` call binds to the
#: currently-running loop, so a process that runs multiple loops (e.g. tests)
#: must drain the set across the loop boundary.
_producer_tasks: set[asyncio.Task[None]] = set()


def create_chat_completions_assistant_message_stream(
    options: ChatCompletionsModelOptions,
    context: Context,
    abort: asyncio.Event | None = None,
) -> AssistantMessageStream:
    """Build an
    :class:`~otter_ai_core.assistant_message_stream.AssistantMessageStream`
    for a Chat Completions model.

    Synchronous; returns immediately and spawns its producer via
    :func:`asyncio.create_task`. Honours the
    :data:`~otter_ai_core.assistant_message_stream.AssistantMessageStreamFnBuilder`
    contract — it never raises.

    ``abort`` is the cooperative-abort signal (an :class:`asyncio.Event`); when
    omitted a fresh, unset event is created and the stream runs to
    completion (the event is never set unless a caller holds a reference).
    """
    if abort is None:
        abort = asyncio.Event()
    stream: AssistantMessageStream
    writer: AssistantMessageWriter
    stream, writer = create_stream()
    task = asyncio.create_task(_run(writer, options, context, abort))
    _producer_tasks.add(task)
    task.add_done_callback(_producer_tasks.discard)
    return stream


# --------------------------------------------------------------------------- #
# Producer task
# --------------------------------------------------------------------------- #


async def _run(
    writer: AssistantMessageWriter,
    options: ChatCompletionsModelOptions,
    context: Context,
    abort: asyncio.Event,
) -> None:
    output = _skeleton(options)
    try:
        await _produce(writer, output, options, context, abort)
    except Exception as exc:  # noqa: BLE001 — the seam must never raise.
        output.stop_reason = StopReason.Aborted if abort.is_set() else StopReason.Error
        output.error_message = _format_error(exc)
        writer.push(
            AssistantErrorEvent(
                role="assistant",
                type="error",
                reason="aborted" if output.stop_reason == "aborted" else "error",
                error=output,
            )
        )
    finally:
        writer.end()


async def _produce(
    writer: AssistantMessageWriter,
    output: AssistantMessage,
    options: ChatCompletionsModelOptions,
    context: Context,
    abort: asyncio.Event,
) -> None:
    model = options.model
    api_key = model.api_key
    if not api_key:
        raise RuntimeError(f"No API key for provider: {model.provider}")

    compat = resolve_compat(model.compat)
    headers = _build_headers(
        model,
        model.session_id if model.cache_retention != "none" else None,
        compat.send_session_affinity_headers,
    )
    params = build_params(model, context, compat)

    if options.hooks.on_payload is not None:
        replaced = await options.hooks.on_payload(
            OnPayloadEvent(payload=params, model=model)
        )
        if replaced is not None:
            params = replaced

    timeout_seconds = (
        (model.timeout_ms / 1000.0)
        if model.timeout_ms is not None
        else _DEFAULT_TIMEOUT_SECONDS
    )
    max_retries = model.max_retries or 0
    max_retry_delay_seconds = (
        (model.max_retry_delay_ms / 1000.0)
        if model.max_retry_delay_ms is not None
        else _DEFAULT_MAX_RETRY_DELAY_SECONDS
    )

    client = _create_client(model, api_key, headers, timeout_seconds)
    async with client:
        response = await _send_with_retries(
            client, params, abort, max_retries, max_retry_delay_seconds
        )
        if options.hooks.on_response is not None:
            await options.hooks.on_response(
                OnResponseEvent(
                    status=response.status_code,
                    headers=dict(response.headers),
                    model=model,
                )
            )

        writer.push(AssistantStartEvent(role="assistant", type="start", partial=output))
        await _consume_stream(writer, output, response, model, abort)


# --------------------------------------------------------------------------- #
# Transport: send + retry
# --------------------------------------------------------------------------- #


async def _send_with_retries(
    client: httpx.AsyncClient,
    params: dict[str, Any],
    abort: asyncio.Event,
    max_retries: int,
    max_retry_delay_seconds: float,
) -> httpx.Response:
    """Send the streaming request, retrying transient failures.

    On a retryable status (429/5xx) honour ``Retry-After`` (seconds). If the
    delay exceeds ``max_retry_delay_seconds`` fail immediately so the caller
    surfaces it (pi-ai parity). Exponential backoff with jitter fills the gaps
    where the server gives no delay. Cooperative abort is honoured before each
    send. The returned :class:`httpx.Response` is a streaming response the
    caller must close.
    """
    body = json.dumps(params).encode("utf-8")
    request = client.build_request("POST", "chat/completions", content=body)
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        if abort.is_set():
            raise RuntimeError("Request was aborted")
        try:
            response = await client.send(request, stream=True)
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= max_retries:
                raise
            await _sleep_or_abort(
                abort, _backoff_seconds(attempt, max_retry_delay_seconds)
            )
            continue

        if response.status_code in _RETRY_STATUS_CODES and attempt < max_retries:
            await response.aclose()
            delay = _retry_after_seconds(response.headers.get("Retry-After"))
            if delay is not None and delay > max_retry_delay_seconds:
                raise RuntimeError(
                    f"Server requested retry delay of {delay:.1f}s exceeding cap "
                    f"of {max_retry_delay_seconds:.1f}s"
                )
            if delay is None:
                delay = _backoff_seconds(attempt, max_retry_delay_seconds)
            await _sleep_or_abort(abort, min(delay, max_retry_delay_seconds))
            continue

        if response.status_code >= 400:
            content = await _read_error_body(response)
            raise _http_status_error(response.status_code, content)

        return response

    raise last_error if last_error else RuntimeError("Request failed after retries")


def _http_status_error(status: int, content: str) -> Exception:
    text = content.strip()
    message = f"HTTP {status}"
    if text:
        message = f"{message}: {text}"
    return RuntimeError(message)


async def _read_error_body(response: httpx.Response) -> str:
    try:
        return (await response.aread()).decode("utf-8", errors="replace")
    finally:
        await response.aclose()


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        # HTTP-date form is rare in practice; treat as no explicit delay.
        return None


def _backoff_seconds(attempt: int, cap: float) -> float:
    base = min(cap, (2**attempt) * 0.5)
    return random.uniform(0, base)


async def _sleep_or_abort(abort: asyncio.Event, seconds: float) -> None:
    """Sleep, but raise immediately if the abort signal fires during the delay.

    A retry backoff interrupted by an abort must surface the abort on the spot
    rather than continuing to the next send attempt.
    """
    if seconds <= 0:
        return
    try:
        await asyncio.wait_for(
            asyncio.create_task(_wait_for_abort(abort)), timeout=seconds
        )
    except TimeoutError:
        return
    # The inner task completed before the timeout — the abort signal fired.
    raise RuntimeError("Request was aborted")


async def _wait_for_abort(abort: asyncio.Event) -> None:
    await abort.wait()


# --------------------------------------------------------------------------- #
# SSE consumption + event emission
# --------------------------------------------------------------------------- #


class _StreamingToolCall:
    """Mutable scratch state for an in-progress tool call.

    Holds a *placeholder* :class:`ToolCall` that also lives in
    ``output.content`` (mutated in place as deltas arrive, so the streaming
    ``partial`` snapshot is always current). Scratch fields that otter's
    ``extra="forbid"`` models cannot carry (the partial JSON string, the stream
    index) live here instead. The placeholder IS the finalized call once the
    arguments are parsed at finish time.
    """

    __slots__ = ("placeholder", "partial_args", "stream_index")

    def __init__(self, placeholder: ToolCall, stream_index: int | None) -> None:
        self.placeholder = placeholder
        self.partial_args = ""
        self.stream_index = stream_index

    def finalize_arguments(self) -> None:
        self.placeholder.arguments = parse_streaming_json(self.partial_args)


async def _consume_stream(
    writer: AssistantMessageWriter,
    output: AssistantMessage,
    response: httpx.Response,
    model: ChatCompletionsModel,
    abort: asyncio.Event,
) -> None:
    blocks: list[AssistantContent] = output.content  # the live list
    state = _BlockState()

    def content_index(block: AssistantContent) -> int:
        return blocks.index(block)

    def ensure_text_block() -> TextContent:
        if state.text_block is None:
            state.text_block = TextContent(type="text", text="")
            blocks.append(state.text_block)
            writer.push(
                AssistantTextStartEvent(
                    role="assistant",
                    type="text_start",
                    content_index=content_index(state.text_block),
                    partial=output,
                )
            )
        return state.text_block

    def ensure_thinking_block(signature: str | None) -> ThinkingContent:
        if state.thinking_block is None:
            state.thinking_block = ThinkingContent(
                type="thinking", thinking="", thinking_signature=signature
            )
            blocks.append(state.thinking_block)
            writer.push(
                AssistantThinkingStartEvent(
                    role="assistant",
                    type="thinking_start",
                    content_index=content_index(state.thinking_block),
                    partial=output,
                )
            )
        return state.thinking_block

    def ensure_tool_call_block(delta: dict[str, Any]) -> _StreamingToolCall:
        stream_index = delta.get("index")
        stream_index_int = stream_index if isinstance(stream_index, int) else None
        tc_id = delta.get("id")
        tc_id_str = tc_id if isinstance(tc_id, str) else None

        streaming: _StreamingToolCall | None = None
        if stream_index_int is not None:
            streaming = state.tool_calls_by_index.get(stream_index_int)
        if streaming is None and tc_id_str:
            streaming = state.tool_calls_by_id.get(tc_id_str)
        if streaming is None:
            placeholder = ToolCall(type="tool_call", id="", name="", arguments={})
            streaming = _StreamingToolCall(placeholder, stream_index_int)
            if stream_index_int is not None:
                state.tool_calls_by_index[stream_index_int] = streaming
            if tc_id_str:
                state.tool_calls_by_id[tc_id_str] = streaming
            blocks.append(placeholder)
            state.tool_calls_in_order.append(streaming)
            writer.push(
                AssistantToolCallStartEvent(
                    role="assistant",
                    type="tool_call_start",
                    content_index=content_index(placeholder),
                    partial=output,
                )
            )
        if tc_id_str and not streaming.placeholder.id:
            streaming.placeholder.id = tc_id_str
        return streaming

    has_finish_reason = False
    try:
        async for payload in iter_sse_events(response):
            if abort.is_set():
                raise RuntimeError("Request was aborted")
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if not isinstance(chunk, dict):
                continue

            _capture_meta(chunk, output, model)

            choices = chunk.get("choices")
            choice = choices[0] if isinstance(choices, list) and choices else None
            if choice and isinstance(choice, dict):
                choice_usage = choice.get("usage")
                if not chunk.get("usage") and choice_usage:
                    output.usage = parse_chunk_usage(choice_usage, model)

                finish_reason = choice.get("finish_reason")
                if finish_reason:
                    stop, error_message = map_stop_reason(finish_reason)
                    output.stop_reason = stop
                    if error_message:
                        output.error_message = error_message
                    has_finish_reason = True

                delta = choice.get("delta")
                if isinstance(delta, dict):
                    _apply_delta(
                        delta,
                        output,
                        model,
                        ensure_text_block,
                        ensure_thinking_block,
                        ensure_tool_call_block,
                        writer,
                        content_index,
                    )
    finally:
        await response.aclose()

    # Post-stream validation — each condition raises to route through the
    # producer's error path.
    if abort.is_set():
        raise RuntimeError("Request was aborted")
    if output.stop_reason == "aborted":
        raise RuntimeError("Request was aborted")
    if output.stop_reason == "error":
        raise RuntimeError(
            output.error_message or "Provider returned an error stop reason"
        )
    if not has_finish_reason:
        raise RuntimeError("Stream ended without finish_reason")

    _finish_blocks(state, blocks, output, writer)

    writer.push(
        AssistantDoneEvent(
            role="assistant",
            type="done",
            reason=output.stop_reason,
            message=output,
        )
    )


class _BlockState:
    """Tracks the currently-open text/thinking/tool-call blocks for emit/close."""

    __slots__ = (
        "text_block",
        "thinking_block",
        "tool_calls_by_index",
        "tool_calls_by_id",
        "tool_calls_in_order",
    )

    def __init__(self) -> None:
        self.text_block: TextContent | None = None
        self.thinking_block: ThinkingContent | None = None
        self.tool_calls_by_index: dict[int, _StreamingToolCall] = {}
        self.tool_calls_by_id: dict[str, _StreamingToolCall] = {}
        self.tool_calls_in_order: list[_StreamingToolCall] = []


def _capture_meta(
    chunk: dict[str, Any], output: AssistantMessage, model: ChatCompletionsModel
) -> None:
    chunk_id = chunk.get("id")
    if isinstance(chunk_id, str) and chunk_id and not output.response_id:
        output.response_id = chunk_id
    chunk_model = chunk.get("model")
    if (
        isinstance(chunk_model, str)
        and chunk_model
        and chunk_model != model.id
        and not output.response_model
    ):
        output.response_model = chunk_model
    raw_usage = chunk.get("usage")
    if raw_usage:
        output.usage = parse_chunk_usage(raw_usage, model)


def _apply_delta(
    delta: dict[str, Any],
    output: AssistantMessage,
    model: ChatCompletionsModel,
    ensure_text_block: Any,
    ensure_thinking_block: Any,
    ensure_tool_call_block: Any,
    writer: AssistantMessageWriter,
    content_index: Any,
) -> None:
    content = delta.get("content")
    if isinstance(content, str) and content:
        block = ensure_text_block()
        block.text += content
        writer.push(
            AssistantTextDeltaEvent(
                role="assistant",
                type="text_delta",
                content_index=content_index(block),
                delta=content,
                partial=output,
            )
        )

    # Reasoning in any of the known fields (first non-empty wins).
    for field in _REASONING_FIELDS:
        value = delta.get(field)
        if isinstance(value, str) and value:
            signature = (
                "reasoning_content"
                if (model.provider == "opencode-go" and field == "reasoning")
                else field
            )
            block = ensure_thinking_block(signature)
            block.thinking += value
            writer.push(
                AssistantThinkingDeltaEvent(
                    role="assistant",
                    type="thinking_delta",
                    content_index=content_index(block),
                    delta=value,
                    partial=output,
                )
            )
            break

    tool_calls = delta.get("tool_calls")
    if isinstance(tool_calls, list):
        for tc_delta in tool_calls:
            if not isinstance(tc_delta, dict):
                continue
            streaming = ensure_tool_call_block(tc_delta)
            function = tc_delta.get("function")
            args_chunk = ""
            if isinstance(function, dict):
                name = function.get("name")
                if isinstance(name, str) and name and not streaming.placeholder.name:
                    streaming.placeholder.name = name
                arguments = function.get("arguments")
                if isinstance(arguments, str) and arguments:
                    args_chunk = arguments
                    streaming.partial_args += arguments
                    streaming.placeholder.arguments = parse_streaming_json(
                        streaming.partial_args
                    )
            writer.push(
                AssistantToolCallDeltaEvent(
                    role="assistant",
                    type="tool_call_delta",
                    content_index=content_index(streaming.placeholder),
                    delta=args_chunk,
                    partial=output,
                )
            )


def _finish_blocks(
    state: _BlockState,
    blocks: list[AssistantContent],
    output: AssistantMessage,
    writer: AssistantMessageWriter,
) -> None:
    """Emit ``*_end`` events for every open block, finalizing tool-call args."""
    for block in list(blocks):
        idx = blocks.index(block)
        if block is state.text_block:
            writer.push(
                AssistantTextEndEvent(
                    role="assistant",
                    type="text_end",
                    content_index=idx,
                    content=block.text,
                    partial=output,
                )
            )
        elif block is state.thinking_block:
            writer.push(
                AssistantThinkingEndEvent(
                    role="assistant",
                    type="thinking_end",
                    content_index=idx,
                    content=block.thinking,
                    partial=output,
                )
            )
        elif isinstance(block, ToolCall):
            streaming = next(
                (sc for sc in state.tool_calls_in_order if sc.placeholder is block),
                None,
            )
            if streaming is not None:
                streaming.finalize_arguments()
            writer.push(
                AssistantToolCallEndEvent(
                    role="assistant",
                    type="tool_call_end",
                    content_index=idx,
                    tool_call=block,
                    partial=output,
                )
            )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _now_ms() -> int:
    return int(time.time() * 1000)


def _empty_usage() -> Usage:
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


def _skeleton(options: ChatCompletionsModelOptions) -> AssistantMessage:
    model = options.model
    return AssistantMessage(
        role="assistant",
        content=[],
        api=model.api,
        provider=model.provider,
        model=model.id,
        usage=_empty_usage(),
        stop_reason="stop",
        timestamp=_now_ms(),
    )


def _build_headers(
    model: ChatCompletionsModel, session_id: str | None, send_affinity: bool
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if model.headers:
        headers.update(model.headers)
    if session_id and send_affinity:
        headers["session_id"] = session_id
        headers["x-client-request-id"] = session_id
        headers["x-session-affinity"] = session_id
    headers.setdefault("Content-Type", "application/json")
    return headers


def _create_client(
    model: ChatCompletionsModel,
    api_key: str,
    headers: dict[str, str],
    timeout_seconds: float,
) -> httpx.AsyncClient:
    """Build the httpx client. Tests monkeypatch this to inject ``MockTransport``."""
    return httpx.AsyncClient(
        base_url=model.base_url,
        headers={**headers, "Authorization": f"Bearer {api_key}"},
        timeout=httpx.Timeout(timeout_seconds),
    )


def _format_error(exc: Exception) -> str:
    message = str(exc) or repr(exc)
    metadata = getattr(exc, "metadata", None)
    if isinstance(metadata, dict):
        raw = metadata.get("raw")
        if raw:
            message += f"\n{raw}"
    return message


__all__ = ["create_chat_completions_assistant_message_stream"]

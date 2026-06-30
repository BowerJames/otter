"""Shared test helpers: a fake ``AssistantMessageStreamFn`` + builders.

Mirrors the chat-completions / realtime ``_helpers`` pattern (fake the
producer, not the network): :class:`ScriptedStreamFn` emits
:class:`AssistantMessageEvent` s from a test-fed queue and is abort-aware, so
the driver's three-way race is exercised realistically with no real LLM.
"""

from __future__ import annotations

import asyncio
from typing import Any

from otter_ai_core import (
    AssistantMessage,
    Context,
    TextContent,
    ThinkingContent,
    ToolCall,
    Usage,
    UsageCost,
    UserMessage,
    context_item,
    create_stream,
)
from otter_ai_core.assistant_message_stream import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    AssistantMessageEvent,
    AssistantMessageStream,
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

#: Internal sentinels carried on the script queue.
_END = object()
_ABORT = object()


def zero_usage() -> Usage:
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


def make_message(
    *,
    content: list[Any] | None = None,
    stop_reason: str = "stop",
    **overrides: Any,
) -> AssistantMessage:
    base: dict[str, Any] = dict(
        role="assistant",
        content=content if content is not None else [],
        api="chat-completions",
        provider="test",
        model="m",
        usage=zero_usage(),
        stop_reason=stop_reason,
        timestamp=0,
    )
    base.update(overrides)
    return AssistantMessage(**base)


# --------------------------------------------------------------------------- #
# AssistantMessageEvent builders
# --------------------------------------------------------------------------- #


def start_event(partial: AssistantMessage) -> AssistantStartEvent:
    return AssistantStartEvent(role="assistant", type="start", partial=partial)


def text_start(idx: int, partial: AssistantMessage) -> AssistantTextStartEvent:
    return AssistantTextStartEvent(
        role="assistant", type="text_start", content_index=idx, partial=partial
    )


def text_delta(
    idx: int, delta: str, partial: AssistantMessage
) -> AssistantTextDeltaEvent:
    return AssistantTextDeltaEvent(
        role="assistant",
        type="text_delta",
        content_index=idx,
        delta=delta,
        partial=partial,
    )


def text_end(
    idx: int, content: str, partial: AssistantMessage
) -> AssistantTextEndEvent:
    return AssistantTextEndEvent(
        role="assistant",
        type="text_end",
        content_index=idx,
        content=content,
        partial=partial,
    )


def thinking_start(idx: int, partial: AssistantMessage) -> AssistantThinkingStartEvent:
    return AssistantThinkingStartEvent(
        role="assistant", type="thinking_start", content_index=idx, partial=partial
    )


def thinking_delta(
    idx: int, delta: str, partial: AssistantMessage
) -> AssistantThinkingDeltaEvent:
    return AssistantThinkingDeltaEvent(
        role="assistant",
        type="thinking_delta",
        content_index=idx,
        delta=delta,
        partial=partial,
    )


def thinking_end(
    idx: int, content: str, partial: AssistantMessage
) -> AssistantThinkingEndEvent:
    return AssistantThinkingEndEvent(
        role="assistant",
        type="thinking_end",
        content_index=idx,
        content=content,
        partial=partial,
    )


def tool_call_start(idx: int, partial: AssistantMessage) -> AssistantToolCallStartEvent:
    return AssistantToolCallStartEvent(
        role="assistant", type="tool_call_start", content_index=idx, partial=partial
    )


def tool_call_delta(
    idx: int, delta: str, partial: AssistantMessage
) -> AssistantToolCallDeltaEvent:
    return AssistantToolCallDeltaEvent(
        role="assistant",
        type="tool_call_delta",
        content_index=idx,
        delta=delta,
        partial=partial,
    )


def tool_call_end(
    idx: int, tool_call: ToolCall, partial: AssistantMessage
) -> AssistantToolCallEndEvent:
    return AssistantToolCallEndEvent(
        role="assistant",
        type="tool_call_end",
        content_index=idx,
        tool_call=tool_call,
        partial=partial,
    )


def done_event(message: AssistantMessage, reason: str = "stop") -> AssistantDoneEvent:
    return AssistantDoneEvent(
        role="assistant", type="done", reason=reason, message=message
    )


def error_event(
    message: AssistantMessage, reason: str = "error"
) -> AssistantErrorEvent:
    return AssistantErrorEvent(
        role="assistant", type="error", reason=reason, error=message
    )


# --------------------------------------------------------------------------- #
# Context / content builders
# --------------------------------------------------------------------------- #


def text_block(text: str = "") -> TextContent:
    return TextContent(type="text", text=text)


def thinking_block(text: str = "", signature: str | None = None) -> ThinkingContent:
    return ThinkingContent(type="thinking", thinking=text, thinking_signature=signature)


def tool_call(
    id: str = "tc1", name: str = "do_it", arguments: dict[str, Any] | None = None
) -> ToolCall:
    return ToolCall(type="tool_call", id=id, name=name, arguments=arguments or {})


def simple_context(*messages: Any, system_prompt: str | None = None) -> Context:
    items: list[Any] = []
    for i, msg in enumerate(messages):
        items.append(context_item(message=msg, id=f"seed-{i}"))
    return Context(system_prompt=system_prompt, items=items, tools=[])


def user_text(text: str, timestamp: int = 0) -> UserMessage:
    return UserMessage(role="user", content=text, timestamp=timestamp)


# --------------------------------------------------------------------------- #
# Fake producer
# --------------------------------------------------------------------------- #


class ScriptedStreamFn:
    """An abort-aware :data:`AssistantMessageStreamFn` fed from a queue.

    Feed events with :meth:`feed`; signal a clean end (no terminal event) with
    :meth:`end`. When the per-response ``abort`` fires and ``honor_abort`` is
    set (default), the producer emits an ``aborted`` terminal and stops —
    mirroring a conforming producer that honours the abort contract.

    Records every ``context`` it is started with (``started``) and counts
    aborts observed (``aborts_received``) for assertions.
    """

    def __init__(self, *, honor_abort: bool = True) -> None:
        self.honor_abort = honor_abort
        self.started: list[Context] = []
        self.aborts_received = 0
        self._queue: asyncio.Queue[Any] = asyncio.Queue()

    def feed(self, *events: AssistantMessageEvent) -> None:
        for event in events:
            self._queue.put_nowait(event)

    def end(self) -> None:
        self._queue.put_nowait(_END)

    async def _next(self, abort: asyncio.Event) -> Any:
        getter = asyncio.create_task(self._queue.get())
        aborter = asyncio.create_task(abort.wait())
        try:
            done, _pending = await asyncio.wait(
                {getter, aborter}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in (getter, aborter):
                if not task.done():
                    task.cancel()
                await _suppress_task(task)
        # The abort path fires only if the abort signal *actually* fired. A
        # cancelled wait task is ``done`` regardless, so checking
        # ``aborter.done()`` here would misroute every getter-won race to
        # ``_ABORT``; ``abort.is_set()`` is the truth independent of
        # cancellation state.
        if abort.is_set():
            if self.honor_abort:
                self.aborts_received += 1
                return _ABORT
            # ``honor_abort=False``: still prefer a queued item if present.
        if getter in done:
            return getter.result()
        return _END

    def __call__(
        self, context: Context, abort: asyncio.Event
    ) -> AssistantMessageStream:
        self.started.append(context)
        stream: AssistantMessageStream
        stream, writer = _create_stream()

        async def produce() -> None:
            while True:
                nxt = await self._next(abort)
                if nxt is _ABORT:
                    writer.push(
                        error_event(make_message(stop_reason="aborted"), "aborted")
                    )
                    break
                if nxt is _END or nxt is None:
                    break
                writer.push(nxt)
                if isinstance(nxt, (AssistantDoneEvent, AssistantErrorEvent)):
                    break
            writer.end()

        asyncio.create_task(produce())
        return stream


# Local alias avoids shadowing the builder import name in tests.
def _create_stream() -> Any:
    return create_stream()


async def _suppress_task(task: asyncio.Task[Any]) -> None:
    try:
        await task
    except BaseException:  # noqa: BLE001 — intentional suppression.
        pass


# --------------------------------------------------------------------------- #
# Connection-driving conveniences
# --------------------------------------------------------------------------- #


async def take(conn: Any, n: int) -> list[Any]:
    """Collect the next ``n`` inbound events from a connection."""
    out: list[Any] = []
    for _ in range(n):
        out.append(await anext(conn))
    return out


async def drain(conn: Any) -> list[Any]:
    """Collect every remaining inbound event until the connection ends."""
    return [event async for event in conn]


__all__ = [
    "Context",
    "ScriptedStreamFn",
    "TextContent",
    "ThinkingContent",
    "ToolCall",
    "Usage",
    "UserMessage",
    "drain",
    "done_event",
    "error_event",
    "make_message",
    "simple_context",
    "start_event",
    "take",
    "text_block",
    "text_delta",
    "text_end",
    "text_start",
    "thinking_block",
    "thinking_delta",
    "thinking_end",
    "thinking_start",
    "tool_call",
    "tool_call_delta",
    "tool_call_end",
    "tool_call_start",
    "user_text",
    "zero_usage",
]

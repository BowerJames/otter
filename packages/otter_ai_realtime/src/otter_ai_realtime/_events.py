"""Bidirectional Realtime wire-format ↔ otter event translation.

This module is the **single** place that knows the OpenAI-Realtime wire
format. Adding a variant provider (one that follows the same event names)
requires no changes elsewhere in the package.

Inbound (server → client)
-------------------------
:class:`InboundTranslator` is stateful across a connection: it owns the
in-progress :class:`~otter_ai_core.AssistantMessage` ``partial`` for the
current response and the flat ``content`` block list, and maps each Realtime
server frame to zero or more otter
:class:`~otter_ai_core.model_connection.ServerEvent` s. v1 maps the text and
tool-call response lifecycles plus ``conversation.item.created`` and
top-level ``error``.

Outbound (client → server)
--------------------------
:func:`client_event_to_frame` maps each otter
:class:`~otter_ai_core.model_connection.ClientEvent` to its Realtime frame.

Content-index mapping
---------------------
Realtime addresses content parts within an output item; otter flattens every
assistant content block into one ``partial.content`` list. v1 maps the
flat list position directly (single text message and/or function calls per
response) — ``content_index`` on the emitted events is the position in
``partial.content``.
"""

from __future__ import annotations

import time
from typing import Any

from otter_ai_core import (
    AssistantMessage,
    ContextItem,
    StopReason,
    TextContent,
    ToolCall,
    Usage,
    UsageCost,
    context_item,
)
from otter_ai_core.context import ContentType
from otter_ai_core.model_connection import (
    AbortResponseEvent,
    ClientEvent,
    ConnectionErrorEvent,
    ContextItemAddedEvent,
    ContextItemAddEvent,
    ResponseAbortedEvent,
    ResponseCreate,
    ResponseDoneEvent,
    ResponseErrorEvent,
    ResponseStartedEvent,
    ResponseTextDoneEvent,
    ResponseTextStartEvent,
    ResponseTextUpdatedEvent,
    ResponseToolCallDoneEvent,
    ResponseToolCallStartEvent,
    ResponseToolCallUpdateEvent,
    ServerEvent,
)
from otter_ai_realtime._json import parse_streaming_json

#: Realtime server frame ``type`` values this translator recognises.
_RESPONSE_STARTED = "response.created"
_OUTPUT_ITEM_ADDED = "response.output_item.added"
_CONTENT_PART_ADDED = "response.content_part.added"
_TEXT_DELTA = "response.text.delta"
_TEXT_DONE = "response.text.done"
_CONTENT_PART_DONE = "response.content_part.done"
_FC_ARGS_DELTA = "response.function_call_arguments.delta"
_FC_ARGS_DONE = "response.function_call_arguments.done"
_OUTPUT_ITEM_DONE = "response.output_item.done"
_RESPONSE_COMPLETED = "response.completed"
_RESPONSE_CANCELLED = "response.cancelled"
_ITEM_CREATED = "conversation.item.created"
_ERROR = "error"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _zero_usage() -> Usage:
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


class _Provenance:
    """The inert assistant-message provenance carried by emitted partials."""

    __slots__ = ("api", "provider", "model")

    def __init__(self, model: Any) -> None:
        self.api = getattr(model, "api", "realtime")
        self.provider = getattr(model, "provider", "")
        self.model = getattr(model, "id", "")


class InboundTranslator:
    """Stateful translator: Realtime server frames → otter ``ServerEvent`` s.

    Construct once per connection. :meth:`feed` returns a list of events
    (usually zero or one; ``output_item.done`` may close an open block in
    addition to any frame-specific event). State is reset on each
    ``response.created``.
    """

    def __init__(self, model: Any) -> None:
        self._prov = _Provenance(model)
        self._partial: AssistantMessage | None = None
        #: content_index of the currently-open tool call (v1: one at a time).
        self._open_tool_index: int | None = None
        #: content_index -> accumulated argument string.
        self._tool_args: dict[int, str] = {}
        #: Tool-call content indices whose ``done`` event has already been
        #: emitted. The Realtime API fires *both* ``function_call_arguments.
        #: done`` and ``output_item.done`` for a function call; without this
        #: guard the second would duplicate the first.
        self._finalized_tool_indices: set[int] = set()

    # -- public ---------------------------------------------------------- #

    def feed(self, frame: dict[str, Any]) -> list[ServerEvent]:
        """Map one Realtime server frame to zero or more otter events."""
        kind = frame.get("type")
        if kind == _RESPONSE_STARTED:
            return self._on_response_created(frame)
        if self._partial is None:
            # Frames outside a response we still care about:
            if kind == _ITEM_CREATED:
                return self._on_item_created(frame)
            if kind == _ERROR:
                return self._on_error(frame)
            return []
        if kind == _CONTENT_PART_ADDED:
            return self._on_content_part_added(frame)
        if kind == _TEXT_DELTA:
            return self._on_text_delta(frame)
        if kind == _TEXT_DONE:
            return self._on_text_done(frame)
        if kind == _OUTPUT_ITEM_ADDED:
            return self._on_output_item_added(frame)
        if kind == _FC_ARGS_DELTA:
            return self._on_fc_args_delta(frame)
        if kind == _FC_ARGS_DONE:
            return self._on_fc_args_done(frame)
        if kind == _OUTPUT_ITEM_DONE:
            return self._on_output_item_done(frame)
        if kind == _CONTENT_PART_DONE:
            return []
        if kind == _RESPONSE_COMPLETED:
            return self._on_response_completed(frame)
        if kind == _RESPONSE_CANCELLED:
            return self._on_response_cancelled(frame)
        if kind == _ITEM_CREATED:
            return self._on_item_created(frame)
        if kind == _ERROR:
            return self._on_error(frame)
        return []

    # -- response lifecycle --------------------------------------------- #

    def _on_response_created(self, frame: dict[str, Any]) -> list[ServerEvent]:
        response = frame.get("response") or {}
        self._partial = AssistantMessage(
            role="assistant",
            content=[],
            api=self._prov.api,
            provider=self._prov.provider,
            model=self._prov.model,
            response_id=response.get("id")
            if isinstance(response.get("id"), str)
            else None,
            usage=_zero_usage(),
            stop_reason=StopReason.Stop,
            timestamp=_now_ms(),
        )
        self._open_tool_index = None
        self._tool_args.clear()
        self._finalized_tool_indices.clear()
        return [
            ResponseStartedEvent(
                type="response.started", role="assistant", partial=self._partial
            )
        ]

    def _on_content_part_added(self, frame: dict[str, Any]) -> list[ServerEvent]:
        assert self._partial is not None
        part = frame.get("part") or {}
        if part.get("type") != "text":
            return []
        block = TextContent(type="text", text="")
        self._partial.content.append(block)
        idx = self._partial.content.index(block)
        return [
            ResponseTextStartEvent(
                type="response.text_content.started",
                role="assistant",
                content_type=ContentType.Text,
                content_index=idx,
                partial=self._partial,
            )
        ]

    def _on_text_delta(self, frame: dict[str, Any]) -> list[ServerEvent]:
        assert self._partial is not None
        delta = frame.get("delta")
        if not isinstance(delta, str) or not delta:
            return []
        block = self._current_text_block()
        if block is None:
            block = TextContent(type="text", text="")
            self._partial.content.append(block)
        block.text += delta
        idx = self._partial.content.index(block)
        return [
            ResponseTextUpdatedEvent(
                type="response.text_content.updated",
                role="assistant",
                content_type=ContentType.Text,
                content_index=idx,
                partial=self._partial,
            )
        ]

    def _on_text_done(self, frame: dict[str, Any]) -> list[ServerEvent]:
        assert self._partial is not None
        block = self._current_text_block()
        if block is not None:
            text = frame.get("text")
            if isinstance(text, str):
                block.text = text
            idx = self._partial.content.index(block)
            return [
                ResponseTextDoneEvent(
                    type="response.text_content.done",
                    role="assistant",
                    content_type=ContentType.Text,
                    content_index=idx,
                    partial=self._partial,
                )
            ]
        return []

    def _on_output_item_added(self, frame: dict[str, Any]) -> list[ServerEvent]:
        assert self._partial is not None
        item = frame.get("item") or {}
        if item.get("type") != "function_call":
            return []
        call_id = item.get("call_id")
        placeholder = ToolCall(
            type="tool_call",
            id=call_id if isinstance(call_id, str) else "",
            name=item.get("name") if isinstance(item.get("name"), str) else "",
            arguments={},
        )
        self._partial.content.append(placeholder)
        idx = self._partial.content.index(placeholder)
        self._open_tool_index = idx
        self._tool_args[idx] = ""
        return [
            ResponseToolCallStartEvent(
                type="response.tool_call.started",
                role="assistant",
                content_type=ContentType.ToolCall,
                content_index=idx,
                partial=self._partial,
            )
        ]

    def _on_fc_args_delta(self, frame: dict[str, Any]) -> list[ServerEvent]:
        assert self._partial is not None
        idx = self._resolve_tool_index(frame)
        if idx is None:
            return []
        delta = frame.get("delta")
        if not isinstance(delta, str):
            return []
        self._tool_args[idx] = self._tool_args.get(idx, "") + delta
        block = self._partial.content[idx]
        assert isinstance(block, ToolCall)
        block.arguments = parse_streaming_json(self._tool_args[idx])
        return [
            ResponseToolCallUpdateEvent(
                type="response.tool_call.updated",
                role="assistant",
                content_type=ContentType.ToolCall,
                content_index=idx,
                partial=self._partial,
            )
        ]

    def _on_fc_args_done(self, frame: dict[str, Any]) -> list[ServerEvent]:
        return self._finalize_tool_call(frame)

    def _on_output_item_done(self, frame: dict[str, Any]) -> list[ServerEvent]:
        assert self._partial is not None
        item = frame.get("item") or {}
        if item.get("type") == "function_call":
            return self._finalize_tool_call(item)
        return []

    def _finalize_tool_call(self, frame: dict[str, Any]) -> list[ServerEvent]:
        assert self._partial is not None
        idx = self._resolve_tool_index(frame)
        if idx is None:
            return []
        # Idempotent: the Realtime API fires both function_call_arguments.done
        # and output_item.done for the same call — emit done only once.
        if idx in self._finalized_tool_indices:
            return []
        block = self._partial.content[idx]
        assert isinstance(block, ToolCall)
        raw = frame.get("arguments")
        if isinstance(raw, str) and raw:
            self._tool_args[idx] = raw
            block.arguments = parse_streaming_json(raw)
        if isinstance(frame.get("call_id"), str):
            block.id = frame["call_id"]
        if isinstance(frame.get("name"), str):
            block.name = frame["name"]
        self._open_tool_index = None
        self._finalized_tool_indices.add(idx)
        return [
            ResponseToolCallDoneEvent(
                type="response.tool_call.done",
                role="assistant",
                content_type=ContentType.ToolCall,
                content_index=idx,
                partial=self._partial,
            )
        ]

    def _resolve_tool_index(self, frame: dict[str, Any]) -> int | None:
        if self._open_tool_index is not None:
            return self._open_tool_index
        assert self._partial is not None
        for i, block in enumerate(self._partial.content):
            if isinstance(block, ToolCall):
                return i
        return None

    def _on_response_completed(self, frame: dict[str, Any]) -> list[ServerEvent]:
        assert self._partial is not None
        partial = self._partial
        has_tool_calls = any(isinstance(b, ToolCall) for b in partial.content)
        reason = StopReason.ToolUse if has_tool_calls else StopReason.Stop
        partial.stop_reason = reason
        self._partial = None
        self._open_tool_index = None
        self._tool_args.clear()
        self._finalized_tool_indices.clear()
        return [
            ResponseDoneEvent(
                type="response.done",
                role="assistant",
                reason=reason,
                partial=partial,
            )
        ]

    def _on_response_cancelled(self, frame: dict[str, Any]) -> list[ServerEvent]:
        assert self._partial is not None
        partial = self._partial
        partial.stop_reason = StopReason.Aborted
        self._partial = None
        self._open_tool_index = None
        self._tool_args.clear()
        self._finalized_tool_indices.clear()
        return [
            ResponseAbortedEvent(
                type="response.aborted",
                role="assistant",
                reason=StopReason.Aborted,
                partial=partial,
            )
        ]

    def _on_error(self, frame: dict[str, Any]) -> list[ServerEvent]:
        err = frame.get("error") or {}
        message = err.get("message") if isinstance(err, dict) else None
        if not isinstance(message, str):
            message = (
                frame.get("message")
                if isinstance(frame.get("message"), str)
                else "Realtime error"
            )
        partial = self._partial or _skeleton(self._prov)
        partial.stop_reason = StopReason.Error
        partial.error_message = message
        self._partial = None
        self._open_tool_index = None
        self._tool_args.clear()
        self._finalized_tool_indices.clear()
        return [
            ResponseErrorEvent(
                type="response.error",
                role="assistant",
                reason=StopReason.Error,
                partial=partial,
            )
        ]

    def _on_item_created(self, frame: dict[str, Any]) -> list[ServerEvent]:
        item = frame.get("item") or {}
        built = _wire_item_to_context_item(item, self._prov)
        if built is None:
            return []
        item_id = item.get("id")
        role = built.role
        return [
            ContextItemAddedEvent(
                type="context_item.added",
                item_id=item_id if isinstance(item_id, str) else "",
                role=role,
                item=built,
            )
        ]

    # -- helpers --------------------------------------------------------- #

    def _current_text_block(self) -> TextContent | None:
        assert self._partial is not None
        for block in reversed(self._partial.content):
            if isinstance(block, TextContent):
                return block
        return None


def _skeleton(prov: _Provenance) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[],
        api=prov.api,
        provider=prov.provider,
        model=prov.model,
        usage=_zero_usage(),
        stop_reason=StopReason.Stop,
        timestamp=_now_ms(),
    )


# --------------------------------------------------------------------------- #
# Outbound: otter ClientEvent → Realtime frame
# --------------------------------------------------------------------------- #


def client_event_to_frame(event: ClientEvent) -> dict[str, Any]:
    """Map an otter :class:`ClientEvent` to its Realtime wire frame."""
    if isinstance(event, ContextItemAddEvent):
        return _context_item_to_create_frame(event.item)
    if isinstance(event, ResponseCreate):
        return {"type": "response.create"}
    if isinstance(event, AbortResponseEvent):
        return {"type": "response.cancel"}
    raise TypeError(f"Unsupported client event: {type(event).__name__}")


def _context_item_to_create_frame(item: ContextItem) -> dict[str, Any]:
    """Translate a :class:`ContextItem` into a ``conversation.item.create`` frame.

    Reuses the message→item shaping from :mod:`otter_ai_realtime._messages`
    so replay and caller-driven ``context_item.add`` share one path.
    """
    # Imported lazily to avoid an import cycle at module load
    # (_messages imports only from core; this keeps the call site explicit).
    from otter_ai_realtime._messages import convert_items

    message = item.to_message()
    items = convert_items([message])
    if not items:
        return {
            "type": "conversation.item.create",
            "item": {"type": "message", "role": "user", "content": []},
        }
    return {"type": "conversation.item.create", "item": items[0]}


def _wire_item_to_context_item(
    item: dict[str, Any], prov: _Provenance
) -> ContextItem | None:
    """Best-effort Realtime ``item`` → otter :class:`ContextItem`.

    Returns ``None`` for item shapes v1 does not map (the caller drops them).
    """
    item_type = item.get("type")
    raw_id = item.get("id")
    item_id = raw_id if isinstance(raw_id, str) else ""
    if item_type == "message":
        role = item.get("role")
        content = item.get("content")
        if not isinstance(content, list):
            return None
        text = _join_message_text(content)
        if role == "user":
            return context_item(
                _user_message(text),
                item_id,
            )
        if role == "assistant":
            return context_item(_assistant_text_message(text, prov), item_id)
        return None
    if item_type == "function_call":
        raw_call_id = item.get("call_id")
        raw_name = item.get("name")
        raw_args = item.get("arguments")
        call_id = raw_call_id if isinstance(raw_call_id, str) else ""
        name = raw_name if isinstance(raw_name, str) else ""
        args = parse_streaming_json(raw_args) if isinstance(raw_args, str) else {}
        return context_item(_assistant_tool_message(call_id, name, args, prov), item_id)
    if item_type == "function_call_output":
        raw_call_id = item.get("call_id")
        raw_output = item.get("output")
        call_id = raw_call_id if isinstance(raw_call_id, str) else ""
        output = raw_output if isinstance(raw_output, str) else ""
        return context_item(_tool_result_message(call_id, output), item_id)
    return None


def _join_message_text(content: list[Any]) -> str:
    parts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts)


def _user_message(text: str) -> Any:
    # Imported from core lazily to keep the translator's import surface small.
    from otter_ai_core import UserMessage

    if not text:
        text = ""
    return UserMessage(role="user", content=text, timestamp=_now_ms())


def _assistant_text_message(text: str, prov: _Provenance) -> Any:
    from otter_ai_core import AssistantMessage, TextContent

    content: list[Any] = []
    if text:
        content.append(TextContent(type="text", text=text))
    return AssistantMessage(
        role="assistant",
        content=content,
        api=prov.api,
        provider=prov.provider,
        model=prov.model,
        usage=_zero_usage(),
        stop_reason=StopReason.Stop,
        timestamp=_now_ms(),
    )


def _assistant_tool_message(
    call_id: str, name: str, args: dict[str, Any], prov: _Provenance
) -> Any:
    from otter_ai_core import AssistantMessage, ToolCall

    return AssistantMessage(
        role="assistant",
        content=[ToolCall(type="tool_call", id=call_id, name=name, arguments=args)],
        api=prov.api,
        provider=prov.provider,
        model=prov.model,
        usage=_zero_usage(),
        stop_reason=StopReason.ToolUse,
        timestamp=_now_ms(),
    )


def _tool_result_message(call_id: str, output: str) -> Any:
    from otter_ai_core import TextContent, ToolResultMessage

    content: list[Any] = []
    if output:
        content.append(TextContent(type="text", text=output))
    return ToolResultMessage(
        role="tool_result",
        tool_call_id=call_id,
        tool_name="",
        content=content,
        is_error=False,
        timestamp=_now_ms(),
    )


def connection_error(message: str, reason: str) -> ConnectionErrorEvent:
    """Build a :class:`ConnectionErrorEvent` (transport-level failure)."""
    return ConnectionErrorEvent(type="connection.error", message=message, reason=reason)


__all__ = [
    "InboundTranslator",
    "client_event_to_frame",
    "connection_error",
]

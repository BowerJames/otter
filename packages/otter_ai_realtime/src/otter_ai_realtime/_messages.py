"""Context → Realtime wire-format translation.

Two responsibilities:

1. :func:`convert_tools` — pure shaping of otter :class:`~otter_ai_core.Tool`
   into Realtime ``session.update`` ``tools[]`` entries. Note the Realtime API
   flattens ``name``/``description``/``parameters`` directly onto the tool
   object (unlike Chat Completions, which nests them under ``function``).
2. :func:`convert_items` — replay-safe translation of
   :class:`~otter_ai_core.ContextItem` items into Realtime
   ``conversation.item.create`` items. Runs
   :func:`otter_ai_core.normalize_messages` first (drops errored/aborted
   assistant turns, fills orphan tool results), then maps each message to one
   or more Realtime items.

v1 is **text-only**: encountering an :class:`~otter_ai_core.ImageContent`
raises :class:`ValueError` (the caller — the seam — encodes this as a
:class:`~otter_ai_core.model_connection.ConnectionErrorEvent`).
"""

from __future__ import annotations

import json
from typing import Any

from otter_ai_core import (
    AssistantMessage,
    ImageContent,
    Message,
    TextContent,
    Tool,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    normalize_messages,
)

#: v1 is text-only. Images are rejected until an audio/multimodal story exists.
_IMAGE_UNSUPPORTED = "otter-ai-realtime v1 is text-only: image content is not supported"


def _check_text_only(content: list[Any]) -> None:
    for block in content:
        if isinstance(block, ImageContent):
            raise ValueError(_IMAGE_UNSUPPORTED)


def convert_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    """Shape otter tools into Realtime ``session.update`` ``tools[]``.

    The Realtime API flattens ``name``/``description``/``parameters`` onto the
    tool object (no ``function`` nesting).
    """
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        for tool in tools
    ]


def convert_items(messages: list[Message]) -> list[dict[str, Any]]:
    """Translate a message list into Realtime ``conversation.item.create`` items.

    Runs :func:`otter_ai_core.normalize_messages` first (opt-in replay prep),
    then maps each message. An assistant message carrying both text and tool
    calls becomes a message item followed by one ``function_call`` item per
    call.
    """
    normalized = normalize_messages(messages)
    items: list[dict[str, Any]] = []
    for msg in normalized:
        if isinstance(msg, UserMessage):
            items.extend(_convert_user_message(msg))
        elif isinstance(msg, AssistantMessage):
            items.extend(_convert_assistant_message(msg))
        elif isinstance(msg, ToolResultMessage):
            items.append(_convert_tool_result(msg))
    return items


def _convert_user_message(msg: UserMessage) -> list[dict[str, Any]]:
    text = _user_text(msg)
    if not text:
        return []
    return [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": text}],
        }
    ]


def _user_text(msg: UserMessage) -> str:
    if isinstance(msg.content, str):
        return msg.content
    _check_text_only(list(msg.content))
    return "\n".join(
        b.text for b in msg.content if isinstance(b, TextContent) and b.text
    )


def _convert_assistant_message(msg: AssistantMessage) -> list[dict[str, Any]]:
    _check_text_only(list(msg.content))
    items: list[dict[str, Any]] = []
    text_parts = [
        b.text for b in msg.content if isinstance(b, TextContent) and b.text.strip()
    ]
    if text_parts:
        items.append(
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "\n".join(text_parts)}],
            }
        )
    for block in msg.content:
        if isinstance(block, ToolCall):
            items.append(
                {
                    "type": "function_call",
                    "call_id": block.id,
                    "name": block.name,
                    "arguments": json.dumps(block.arguments),
                }
            )
    return items


def _convert_tool_result(msg: ToolResultMessage) -> dict[str, Any]:
    _check_text_only(list(msg.content))
    text = "\n".join(
        b.text for b in msg.content if isinstance(b, TextContent) and b.text
    )
    return {
        "type": "function_call_output",
        "call_id": msg.tool_call_id,
        "output": text if text else "",
    }


def convert_items_to_create_frames(messages: list[Message]) -> list[dict[str, Any]]:
    """Wrap each replay item as a ``conversation.item.create`` frame.

    Used by the connection seam to replay a seeded :class:`~otter_ai_core.Context`
    into a freshly-opened realtime session (full replay).
    """
    return [
        {"type": "conversation.item.create", "item": item}
        for item in convert_items(messages)
    ]


__all__ = ["convert_items", "convert_items_to_create_frames", "convert_tools"]

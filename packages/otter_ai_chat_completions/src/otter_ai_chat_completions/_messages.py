"""Context → Chat Completions wire translation.

Two responsibilities:

1. :func:`transform_messages` — a private, model-aware replay-prep pass. It
   downgrades images for non-vision models, handles cross-model thinking
   blocks, inserts synthetic tool results for orphaned tool calls, and drops
   errored/aborted assistant turns. It is **deliberately not** a re-export of
   :func:`otter_ai.normalize_messages`: that public API is opt-in only and the
   in-package provider always needs a replay-safe list.
2. :func:`convert_messages` / :func:`convert_tools` / :func:`has_tool_history`
   — pure shaping into Chat Completions request bodies.

This is a Python port of pi-ai's ``transform-messages.ts`` and the
``convertMessages``/``convertTools``/``hasToolHistory`` helpers in
``openai-completions.ts``.
"""

from __future__ import annotations

import json
import time
from typing import Any

from otter_ai import (
    AssistantContent,
    AssistantMessage,
    ImageContent,
    Message,
    TextContent,
    ThinkingContent,
    Tool,
    ToolCall,
    ToolResultMessage,
    UserContent,
    UserMessage,
)
from otter_ai_chat_completions._compat import ResolvedCompat
from otter_ai_chat_completions.models import ChatCompletionsModel

_NON_VISION_USER_IMAGE_PLACEHOLDER = "(image omitted: model does not support images)"
_NON_VISION_TOOL_IMAGE_PLACEHOLDER = (
    "(tool image omitted: model does not support images)"
)


def has_tool_history(messages: list[Message]) -> bool:
    """Whether the conversation contains any tool calls or tool results."""
    for msg in messages:
        if isinstance(msg, ToolResultMessage):
            return True
        if isinstance(msg, AssistantMessage) and any(
            isinstance(b, ToolCall) for b in msg.content
        ):
            return True
    return False


# --------------------------------------------------------------------------- #
# transform_messages — private model-aware replay prep
# --------------------------------------------------------------------------- #


def _replace_images_with_placeholder(
    content: list[UserContent], placeholder: str
) -> list[TextContent]:
    """Collapse runs of images into a single placeholder text block."""
    result: list[TextContent] = []
    previous_was_placeholder = False
    for block in content:
        if isinstance(block, ImageContent):
            if not previous_was_placeholder:
                result.append(TextContent(type="text", text=placeholder))
            previous_was_placeholder = True
            continue
        # Must be TextContent (UserContent union is text|image).
        assert isinstance(block, TextContent)
        result.append(block)
        previous_was_placeholder = block.text == placeholder
    return result


def _downgrade_unsupported_images(
    messages: list[Message], model: ChatCompletionsModel
) -> list[Message]:
    if "image" in model.input_modalities:
        return list(messages)

    out: list[Message] = []
    for msg in messages:
        if isinstance(msg, AssistantMessage):
            out.append(msg)
            continue
        if isinstance(msg, UserMessage) and isinstance(msg.content, list):
            out.append(
                msg.model_copy(
                    update={
                        "content": _replace_images_with_placeholder(
                            msg.content, _NON_VISION_USER_IMAGE_PLACEHOLDER
                        )
                    }
                )
            )
            continue
        if isinstance(msg, ToolResultMessage):
            out.append(
                msg.model_copy(
                    update={
                        "content": _replace_images_with_placeholder(
                            list(msg.content), _NON_VISION_TOOL_IMAGE_PLACEHOLDER
                        )
                    }
                )
            )
            continue
        out.append(msg)
    return out


def _is_same_model(msg: AssistantMessage, model: ChatCompletionsModel) -> bool:
    return (
        msg.provider == model.provider
        and msg.api == model.api
        and msg.model == model.id
    )


def _transform_assistant_content(
    msg: AssistantMessage, model: ChatCompletionsModel
) -> list[AssistantContent]:
    same_model = _is_same_model(msg, model)
    out: list[AssistantContent] = []
    for block in msg.content:
        if isinstance(block, ThinkingContent):
            # Redacted thinking is opaque encrypted content, valid only same-model.
            if block.redacted:
                if same_model:
                    out.append(block)
                continue
            # Same model: keep signed thinking even when empty (replay continuity).
            if same_model and block.thinking_signature:
                out.append(block)
                continue
            if not block.thinking or not block.thinking.strip():
                continue
            if same_model:
                out.append(block)
            else:
                out.append(TextContent(type="text", text=block.thinking))
            continue
        if isinstance(block, TextContent):
            if same_model:
                out.append(block)
            else:
                out.append(TextContent(type="text", text=block.text))
            continue
        if isinstance(block, ToolCall):
            tc = block
            if not same_model and tc.thought_signature:
                tc = tc.model_copy(update={"thought_signature": None})
            out.append(tc)
            continue
        out.append(block)
    return out


def _synthetic_tool_result(call: ToolCall) -> ToolResultMessage:
    return ToolResultMessage(
        role="tool_result",
        tool_call_id=call.id,
        tool_name=call.name,
        content=[TextContent(type="text", text="No result provided")],
        is_error=True,
        timestamp=int(time.time() * 1000),
    )


def transform_messages(
    messages: list[Message], model: ChatCompletionsModel
) -> list[Message]:
    """Model-aware replay prep (private, in-package counterpart to normalize).

    * Downgrade images for non-vision models.
    * Drop/convert cross-model thinking; strip cross-model ``thought_signature``.
    * Drop errored/aborted assistant turns entirely.
    * Insert synthetic error tool results for orphaned tool calls.
    """
    image_aware = _downgrade_unsupported_images(messages, model)

    # First pass: per-message content transforms.
    transformed: list[Message] = []
    pending_tool_calls: list[ToolCall] = []
    seen_result_ids: set[str] = set()

    def flush_pending() -> None:
        for call in pending_tool_calls:
            if call.id not in seen_result_ids:
                transformed.append(_synthetic_tool_result(call))
        pending_tool_calls.clear()
        seen_result_ids.clear()

    for msg in image_aware:
        if isinstance(msg, AssistantMessage):
            flush_pending()
            if msg.stop_reason in ("error", "aborted"):
                continue
            new_content = _transform_assistant_content(msg, model)
            transformed.append(msg.model_copy(update={"content": new_content}))
            calls = [b for b in new_content if isinstance(b, ToolCall)]
            if calls:
                pending_tool_calls = calls
                seen_result_ids = set()
        elif isinstance(msg, ToolResultMessage):
            seen_result_ids.add(msg.tool_call_id)
            transformed.append(msg)
        else:
            flush_pending()
            transformed.append(msg)
    flush_pending()
    return transformed


# --------------------------------------------------------------------------- #
# convert_messages / convert_tools — wire shaping
# --------------------------------------------------------------------------- #


def _sanitize_for_wire(text: str) -> str:
    """Sanitize user/assistant text before placing it on the wire.

    pi-ai sanitizes Unicode surrogates; otter's Pydantic models already hold
    valid Python ``str`` (which cannot contain lone surrogates), so this is a
    pass-through kept as an explicit seam.
    """
    return text


def _image_data_uri(block: ImageContent) -> str:
    return f"data:{block.mime_type};base64,{block.data}"


def convert_tools(tools: list[Tool], compat: ResolvedCompat) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tool in tools:
        function: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        if compat.supports_strict_mode:
            function["strict"] = False
        out.append({"type": "function", "function": function})
    return out


def convert_messages(
    model: ChatCompletionsModel,
    system_prompt: str | None,
    messages: list[Message],
    compat: ResolvedCompat,
) -> list[dict[str, Any]]:
    """Build the Chat Completions ``messages`` array from a Context.

    Runs :func:`transform_messages` first, then shapes each message for the
    wire. Assistant text content is always emitted as a **plain string**
    (never an array of text parts) — arrays of ``{type:"text"}`` objects are
    non-standard and cause some models to mirror the block structure.
    """
    transformed = transform_messages(messages, model)
    params: list[dict[str, Any]] = []

    if system_prompt:
        role = (
            "developer"
            if (model.reasoning and compat.supports_developer_role)
            else "system"
        )
        params.append({"role": role, "content": _sanitize_for_wire(system_prompt)})

    last_role: str | None = None
    i = 0
    while i < len(transformed):
        msg = transformed[i]

        if (
            compat.requires_assistant_after_tool_result
            and last_role == "tool_result"
            and isinstance(msg, UserMessage)
        ):
            params.append(
                {"role": "assistant", "content": "I have processed the tool results."}
            )

        if isinstance(msg, UserMessage):
            last_role = "user"
            if isinstance(msg.content, str):
                params.append(
                    {"role": "user", "content": _sanitize_for_wire(msg.content)}
                )
            else:
                parts = _convert_user_content(msg.content)
                if parts:
                    params.append({"role": "user", "content": parts})
            i += 1
            continue

        if isinstance(msg, AssistantMessage):
            last_role = "assistant"
            wire = _convert_assistant_message(msg, model, compat)
            if wire is not None:
                params.append(wire)
            i += 1
            continue

        if isinstance(msg, ToolResultMessage):
            # Consume a run of consecutive tool results; collect images.
            image_blocks: list[dict[str, Any]] = []
            j = i
            while j < len(transformed):
                tool_msg = transformed[j]
                if not isinstance(tool_msg, ToolResultMessage):
                    break
                text_result = "\n".join(
                    b.text
                    for b in tool_msg.content
                    if isinstance(b, TextContent) and b.text
                )
                params.append(
                    {
                        "role": "tool",
                        "content": _sanitize_for_wire(
                            text_result if text_result else "(see attached image)"
                        ),
                        "tool_call_id": tool_msg.tool_call_id,
                        **(
                            {"name": tool_msg.tool_name}
                            if (compat.requires_tool_result_name and tool_msg.tool_name)
                            else {}
                        ),
                    }
                )
                if "image" in model.input_modalities:
                    for block in tool_msg.content:
                        if isinstance(block, ImageContent):
                            image_blocks.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": _image_data_uri(block)},
                                }
                            )
                j += 1
            i = j
            if image_blocks:
                if compat.requires_assistant_after_tool_result:
                    params.append(
                        {
                            "role": "assistant",
                            "content": "I have processed the tool results.",
                        }
                    )
                params.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Attached image(s) from tool result:",
                            },
                            *image_blocks,
                        ],
                    }
                )
                last_role = "user"
            else:
                last_role = "tool_result"
            continue

        # Unrecognized message type — pass through as-is defensively.
        last_role = None
        i += 1

    return params


def _convert_user_content(content: list[UserContent]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, TextContent):
            parts.append({"type": "text", "text": _sanitize_for_wire(block.text)})
        elif isinstance(block, ImageContent):
            parts.append(
                {"type": "image_url", "image_url": {"url": _image_data_uri(block)}}
            )
    return parts


def _convert_assistant_message(
    msg: AssistantMessage,
    model: ChatCompletionsModel,
    compat: ResolvedCompat,
) -> dict[str, Any] | None:
    """Shape an assistant message for the wire, or ``None`` to skip it.

    pi-ai notes several providers reject empty assistant messages; we mirror
    that by skipping messages with no content and no tool calls.
    """
    wire: dict[str, Any] = {
        "role": "assistant",
        # Some providers reject ``null``; default to empty string and overwrite
        # below only when there is real text to send.
        "content": "" if compat.requires_assistant_after_tool_result else None,
    }

    text_parts = [
        b for b in msg.content if isinstance(b, TextContent) and b.text.strip()
    ]
    thinking_blocks = [
        b for b in msg.content if isinstance(b, ThinkingContent) and b.thinking.strip()
    ]
    tool_calls = [b for b in msg.content if isinstance(b, ToolCall)]
    assistant_text = "\n".join(b.text for b in text_parts)

    if thinking_blocks and compat.requires_thinking_as_text:
        # Emit thinking as plain text (no tags, to avoid models mimicking them).
        wire["content"] = "\n\n".join(
            _sanitize_for_wire(b.thinking) for b in thinking_blocks
        )
        if assistant_text:
            # Prepend thinking-as-text then the real text. Preserve the
            # plain-string invariant by concatenating rather than nesting.
            wire["content"] = (
                wire["content"] + "\n\n" + _sanitize_for_wire(assistant_text)
            )
    elif thinking_blocks:
        if assistant_text:
            wire["content"] = _sanitize_for_wire(assistant_text)
        # Emit thinking via the first block's signature field (llama.cpp/gpt-oss).
        signature = thinking_blocks[0].thinking_signature
        if model.provider == "opencode-go" and signature == "reasoning":
            signature = "reasoning_content"
        if signature:
            wire[signature] = "\n".join(b.thinking for b in thinking_blocks)
    elif assistant_text:
        wire["content"] = _sanitize_for_wire(assistant_text)

    if tool_calls:
        wire["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments),
                },
            }
            for tc in tool_calls
        ]

    if (
        compat.requires_reasoning_content_on_assistant_messages
        and model.reasoning
        and "reasoning_content" not in wire
    ):
        wire["reasoning_content"] = ""

    content = wire.get("content")
    has_content = content is not None and (
        (isinstance(content, str) and len(content) > 0)
        or (isinstance(content, list) and len(content) > 0)
    )
    if not has_content and "tool_calls" not in wire:
        return None
    return wire

"""Chat Completions compat resolution.

Per issue #13 decision #3, this package performs **no provider/base_url
detection**. ``resolve_compat`` produces a fully-populated
:class:`ResolvedCompat` by overlaying the caller's explicit
:class:`ChatCompletionsCompat` on top of the standard Chat Completions
defaults. This mirrors the structure of pi-ai's ``detectCompat``/``getCompat``
pair but with the detection branch removed — the default set *is* the OpenAI
standard branch.

``ResolvedCompat`` is a frozen dataclass (not a Pydantic model): it is a
runtime value computed once per call, consumed by the translation/transport
layers, and never serialized.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from otter_ai_chat_completions.models import (
    ChatCompletionsCompat,
    ChatTemplateKwargValue,
)


@dataclass(frozen=True)
class ResolvedCompat:
    """Fully-resolved compat: every field populated with a usable value."""

    supports_store: bool
    supports_developer_role: bool
    supports_reasoning_effort: bool
    supports_usage_in_streaming: bool
    max_tokens_field: str  # "max_completion_tokens" | "max_tokens"
    requires_tool_result_name: bool
    requires_assistant_after_tool_result: bool
    requires_thinking_as_text: bool
    requires_reasoning_content_on_assistant_messages: bool
    thinking_format: str
    chat_template_kwargs: dict[str, ChatTemplateKwargValue]
    openrouter_routing: dict[str, Any]
    vercel_gateway_routing: dict[str, Any]
    zai_tool_stream: bool
    supports_strict_mode: bool
    cache_control_format: str | None  # None | "anthropic"
    send_session_affinity_headers: bool
    supports_long_cache_retention: bool


#: The standard Chat Completions default set (the OpenAI-standard branch of
#: pi-ai's ``detectCompat``). Every field the caller leaves unset resolves to
#: these values.
STANDARD_DEFAULTS = ResolvedCompat(
    supports_store=True,
    supports_developer_role=True,
    supports_reasoning_effort=True,
    supports_usage_in_streaming=True,
    max_tokens_field="max_completion_tokens",
    requires_tool_result_name=False,
    requires_assistant_after_tool_result=False,
    requires_thinking_as_text=False,
    requires_reasoning_content_on_assistant_messages=False,
    thinking_format="openai",
    chat_template_kwargs={},
    openrouter_routing={},
    vercel_gateway_routing={},
    zai_tool_stream=False,
    supports_strict_mode=True,
    cache_control_format=None,
    send_session_affinity_headers=False,
    supports_long_cache_retention=True,
)


def resolve_compat(compat: ChatCompletionsCompat | None) -> ResolvedCompat:
    """Overlay ``compat`` on :data:`STANDARD_DEFAULTS`.

    Each compat field is optional; a ``None`` (unset) field falls back to the
    matching standard default. Mutable defaults (``dict``) are copied so the
    resolved value can be safely mutated by the caller without aliasing the
    module-level default.
    """
    if compat is None:
        return ResolvedCompat(
            supports_store=STANDARD_DEFAULTS.supports_store,
            supports_developer_role=STANDARD_DEFAULTS.supports_developer_role,
            supports_reasoning_effort=STANDARD_DEFAULTS.supports_reasoning_effort,
            supports_usage_in_streaming=STANDARD_DEFAULTS.supports_usage_in_streaming,
            max_tokens_field=STANDARD_DEFAULTS.max_tokens_field,
            requires_tool_result_name=STANDARD_DEFAULTS.requires_tool_result_name,
            requires_assistant_after_tool_result=STANDARD_DEFAULTS.requires_assistant_after_tool_result,
            requires_thinking_as_text=STANDARD_DEFAULTS.requires_thinking_as_text,
            requires_reasoning_content_on_assistant_messages=STANDARD_DEFAULTS.requires_reasoning_content_on_assistant_messages,
            thinking_format=STANDARD_DEFAULTS.thinking_format,
            chat_template_kwargs=dict(STANDARD_DEFAULTS.chat_template_kwargs),
            openrouter_routing=dict(STANDARD_DEFAULTS.openrouter_routing),
            vercel_gateway_routing=dict(STANDARD_DEFAULTS.vercel_gateway_routing),
            zai_tool_stream=STANDARD_DEFAULTS.zai_tool_stream,
            supports_strict_mode=STANDARD_DEFAULTS.supports_strict_mode,
            cache_control_format=STANDARD_DEFAULTS.cache_control_format,
            send_session_affinity_headers=STANDARD_DEFAULTS.send_session_affinity_headers,
            supports_long_cache_retention=STANDARD_DEFAULTS.supports_long_cache_retention,
        )

    return ResolvedCompat(
        supports_store=compat.supports_store
        if compat.supports_store is not None
        else STANDARD_DEFAULTS.supports_store,
        supports_developer_role=compat.supports_developer_role
        if compat.supports_developer_role is not None
        else STANDARD_DEFAULTS.supports_developer_role,
        supports_reasoning_effort=compat.supports_reasoning_effort
        if compat.supports_reasoning_effort is not None
        else STANDARD_DEFAULTS.supports_reasoning_effort,
        supports_usage_in_streaming=compat.supports_usage_in_streaming
        if compat.supports_usage_in_streaming is not None
        else STANDARD_DEFAULTS.supports_usage_in_streaming,
        max_tokens_field=compat.max_tokens_field
        if compat.max_tokens_field is not None
        else STANDARD_DEFAULTS.max_tokens_field,
        requires_tool_result_name=compat.requires_tool_result_name
        if compat.requires_tool_result_name is not None
        else STANDARD_DEFAULTS.requires_tool_result_name,
        requires_assistant_after_tool_result=compat.requires_assistant_after_tool_result
        if compat.requires_assistant_after_tool_result is not None
        else STANDARD_DEFAULTS.requires_assistant_after_tool_result,
        requires_thinking_as_text=compat.requires_thinking_as_text
        if compat.requires_thinking_as_text is not None
        else STANDARD_DEFAULTS.requires_thinking_as_text,
        requires_reasoning_content_on_assistant_messages=compat.requires_reasoning_content_on_assistant_messages
        if compat.requires_reasoning_content_on_assistant_messages is not None
        else STANDARD_DEFAULTS.requires_reasoning_content_on_assistant_messages,
        thinking_format=compat.thinking_format
        if compat.thinking_format is not None
        else STANDARD_DEFAULTS.thinking_format,
        chat_template_kwargs=dict(
            compat.chat_template_kwargs
            if compat.chat_template_kwargs is not None
            else STANDARD_DEFAULTS.chat_template_kwargs
        ),
        openrouter_routing=dict(
            compat.openrouter_routing
            if compat.openrouter_routing is not None
            else STANDARD_DEFAULTS.openrouter_routing
        ),
        vercel_gateway_routing=dict(
            compat.vercel_gateway_routing
            if compat.vercel_gateway_routing is not None
            else STANDARD_DEFAULTS.vercel_gateway_routing
        ),
        zai_tool_stream=compat.zai_tool_stream
        if compat.zai_tool_stream is not None
        else STANDARD_DEFAULTS.zai_tool_stream,
        supports_strict_mode=compat.supports_strict_mode
        if compat.supports_strict_mode is not None
        else STANDARD_DEFAULTS.supports_strict_mode,
        cache_control_format=compat.cache_control_format
        if compat.cache_control_format is not None
        else STANDARD_DEFAULTS.cache_control_format,
        send_session_affinity_headers=compat.send_session_affinity_headers
        if compat.send_session_affinity_headers is not None
        else STANDARD_DEFAULTS.send_session_affinity_headers,
        supports_long_cache_retention=compat.supports_long_cache_retention
        if compat.supports_long_cache_retention is not None
        else STANDARD_DEFAULTS.supports_long_cache_retention,
    )

"""Compat resolution — standard defaults + explicit overlay."""

from __future__ import annotations

import pytest

from otter_ai_chat_completions import ChatCompletionsCompat, ChatTemplateKwargVar
from otter_ai_chat_completions._compat import ResolvedCompat, resolve_compat


def test_none_compat_yields_standard_defaults() -> None:
    resolved = resolve_compat(None)
    assert resolved == ResolvedCompat(
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


def test_all_none_compat_yields_standard_defaults() -> None:
    resolved = resolve_compat(ChatCompletionsCompat())
    assert resolved.thinking_format == "openai"
    assert resolved.max_tokens_field == "max_completion_tokens"
    assert resolved.supports_store is True
    assert resolved.supports_long_cache_retention is True


def test_explicit_field_overrides_default() -> None:
    resolved = resolve_compat(
        ChatCompletionsCompat(
            supports_store=False,
            thinking_format="deepseek",
            max_tokens_field="max_tokens",
        )
    )
    assert resolved.supports_store is False
    assert resolved.thinking_format == "deepseek"
    assert resolved.max_tokens_field == "max_tokens"
    # Untouched fields keep their defaults.
    assert resolved.supports_developer_role is True
    assert resolved.supports_reasoning_effort is True


def test_chat_template_kwargs_default_is_empty_dict() -> None:
    assert resolve_compat(None).chat_template_kwargs == {}


def test_chat_template_kwargs_copied_not_aliased() -> None:
    kwargs = {"e": ChatTemplateKwargVar(var="thinking.enabled")}
    resolved = resolve_compat(ChatCompletionsCompat(chat_template_kwargs=kwargs))
    # Mutating the resolved dict must not affect the source compat.
    resolved.chat_template_kwargs["other"] = "x"
    assert "other" not in kwargs


def test_resolved_compat_is_frozen() -> None:
    import dataclasses

    resolved = resolve_compat(None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        resolved.supports_store = False  # type: ignore[misc]

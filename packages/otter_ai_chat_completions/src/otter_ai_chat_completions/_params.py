"""Chat Completions request body construction.

Python port of pi-ai's ``buildParams`` in ``openai-completions.ts``. Produces
the JSON body sent to ``POST {base_url}/chat/completions`` (with
``stream: True``). The transport layer (:mod:`otter_ai_chat_completions.stream`)
then runs the ``on_payload`` hook over the result (which may replace it).

The reasoning (thinking) field is selected by a switch over
``compat.thinking_format`` covering all 10 formats pi-ai supports, including
the generic ``chat-template`` format resolved from ``compat.chat_template_kwargs``.
"""

from __future__ import annotations

from typing import Any

from otter_ai_chat_completions._compat import ResolvedCompat
from otter_ai_chat_completions._messages import (
    convert_messages,
    convert_tools,
    has_tool_history,
)
from otter_ai_chat_completions.models import (
    CHAT_TEMPLATE_THINKING_EFFORT,
    CHAT_TEMPLATE_THINKING_ENABLED,
    ChatCompletionsModel,
    ChatCompletionsReasoningEffort,
    ChatTemplateKwargValue,
    ChatTemplateKwargVar,
)
from otter_ai_core import Context

#: A cache-control marker for Anthropic-style prompt caching.
_AnthropicCacheControl = dict[str, Any]


def _resolve_cache_retention(model: ChatCompletionsModel) -> str:
    return model.cache_retention or "short"


def _get_compat_cache_control(
    compat: ResolvedCompat, cache_retention: str
) -> _AnthropicCacheControl | None:
    if compat.cache_control_format != "anthropic" or cache_retention == "none":
        return None
    ttl = (
        "1h"
        if (cache_retention == "long" and compat.supports_long_cache_retention)
        else None
    )
    marker: dict[str, Any] = {"type": "ephemeral"}
    if ttl:
        marker["ttl"] = ttl
    return marker


def _add_cache_control_to_instruction_message(
    message: dict[str, Any], cache_control: _AnthropicCacheControl
) -> bool:
    return _add_cache_control_to_text_content(message, cache_control)


def _add_cache_control_to_message(
    message: dict[str, Any], cache_control: _AnthropicCacheControl
) -> bool:
    if message.get("role") in ("user", "assistant"):
        return _add_cache_control_to_text_content(message, cache_control)
    return False


def _add_cache_control_to_text_content(
    message: dict[str, Any], cache_control: _AnthropicCacheControl
) -> bool:
    content = message.get("content")
    if isinstance(content, str):
        if len(content) == 0:
            return False
        message["content"] = [
            {"type": "text", "text": content, "cache_control": cache_control}
        ]
        return True
    if not isinstance(content, list):
        return False
    for idx in range(len(content) - 1, -1, -1):
        part = content[idx]
        if isinstance(part, dict) and part.get("type") == "text":
            part["cache_control"] = cache_control
            return True
    return False


def _apply_anthropic_cache_control(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    cache_control: _AnthropicCacheControl,
) -> None:
    # System / developer prompt.
    for message in messages:
        if message.get("role") in ("system", "developer"):
            _add_cache_control_to_instruction_message(message, cache_control)
            break
    # Last tool definition.
    if tools:
        tools[-1]["function"]["cache_control"] = cache_control
    # Last user/assistant conversation message.
    for idx in range(len(messages) - 1, -1, -1):
        message = messages[idx]
        if message.get("role") in ("user", "assistant"):
            if _add_cache_control_to_message(message, cache_control):
                break


def _clamp_openai_prompt_cache_key(session_id: str | None) -> str | None:
    """OpenAI's ``prompt_cache_key`` allows ``[a-zA-Z0-9_,:;-]`` up to 128 chars."""
    if not session_id:
        return None
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_,:;-")
    clamped = "".join(c if c in allowed else "_" for c in session_id)
    return clamped[:128] or None


def _resolve_reasoning_effort(
    model: ChatCompletionsModel, effort: ChatCompletionsReasoningEffort | None
) -> str | None:
    """Map a reasoning effort via ``thinking_level_map`` if present, else raw."""
    if effort is None:
        return None
    mapped = model.thinking_level_map.get(effort) if model.thinking_level_map else None
    if mapped is None:
        return effort
    return mapped


def _resolve_chat_template_kwarg_value(
    model: ChatCompletionsModel,
    effort: ChatCompletionsReasoningEffort | None,
    value: ChatTemplateKwargValue,
) -> Any:
    if not isinstance(value, ChatTemplateKwargVar):
        return value
    if effort is None and value.omit_when_off:
        return _OMIT
    if value.var == CHAT_TEMPLATE_THINKING_ENABLED:
        return effort is not None
    if value.var == CHAT_TEMPLATE_THINKING_EFFORT:
        mapped = _resolve_reasoning_effort(model, effort)
        if mapped is None and value.omit_when_off:
            return _OMIT
        return mapped
    return None


class _OmitSentinel:
    __slots__ = ()


_OMIT: Any = _OmitSentinel()


def _build_chat_template_kwargs(
    model: ChatCompletionsModel,
    effort: ChatCompletionsReasoningEffort | None,
    compat: ResolvedCompat,
) -> dict[str, Any] | None:
    if not compat.chat_template_kwargs:
        return None
    out: dict[str, Any] = {}
    for key, raw_value in compat.chat_template_kwargs.items():
        resolved = _resolve_chat_template_kwarg_value(model, effort, raw_value)
        if resolved is _OMIT or resolved is None:
            continue
        out[key] = resolved
    return out or None


def _apply_thinking(
    params: dict[str, Any],
    model: ChatCompletionsModel,
    compat: ResolvedCompat,
    effort: ChatCompletionsReasoningEffort | None,
) -> None:
    """Mutate ``params`` to add reasoning/thinking fields per ``thinking_format``.

    Faithful port of pi-ai's ``buildParams`` thinking switch. When
    ``reasoning_effort`` is ``None`` some formats still emit an "off" value
    (mirroring pi-ai). Non-reasoning models never emit any thinking field.
    """
    if not model.reasoning:
        return

    fmt = compat.thinking_format

    if fmt == "zai":
        params["thinking"] = {"type": "enabled" if effort else "disabled"}
        if effort and compat.supports_reasoning_effort:
            mapped = _resolve_reasoning_effort(model, effort)
            if mapped is not None:
                params["reasoning_effort"] = mapped
        return

    if fmt == "qwen":
        params["enable_thinking"] = bool(effort)
        return

    if fmt == "qwen-chat-template":
        params["chat_template_kwargs"] = {
            "enable_thinking": bool(effort),
            "preserve_thinking": True,
        }
        return

    if fmt == "chat-template":
        kwargs = _build_chat_template_kwargs(model, effort, compat)
        if kwargs is not None:
            params["chat_template_kwargs"] = kwargs
        return

    if fmt == "deepseek":
        if effort:
            params["thinking"] = {"type": "enabled"}
        elif (
            model.thinking_level_map and model.thinking_level_map.get("off") is not None
        ):
            params["thinking"] = {"type": "disabled"}
        if effort and compat.supports_reasoning_effort:
            mapped = _resolve_reasoning_effort(model, effort)
            if mapped is not None:
                params["reasoning_effort"] = mapped
        return

    if fmt == "openrouter":
        if effort:
            mapped = _resolve_reasoning_effort(model, effort)
            params["reasoning"] = {"effort": mapped if mapped is not None else effort}
        elif (
            model.thinking_level_map and model.thinking_level_map.get("off") is not None
        ):
            params["reasoning"] = {"effort": model.thinking_level_map["off"] or "none"}
        return

    if fmt == "ant-ling":
        if effort:
            mapped = _resolve_reasoning_effort(model, effort)
            if mapped is not None:
                params["reasoning"] = {"effort": mapped}
        return

    if fmt == "together":
        params["reasoning"] = {"enabled": bool(effort)}
        if effort and compat.supports_reasoning_effort:
            mapped = _resolve_reasoning_effort(model, effort)
            if mapped is not None:
                params["reasoning_effort"] = mapped
        return

    if fmt == "string-thinking":
        if effort:
            mapped = _resolve_reasoning_effort(model, effort)
            params["thinking"] = mapped if mapped is not None else effort
        elif (
            model.thinking_level_map and model.thinking_level_map.get("off") is not None
        ):
            params["thinking"] = model.thinking_level_map["off"] or "none"
        return

    # Default: OpenAI-style ``reasoning_effort``.
    if effort and compat.supports_reasoning_effort:
        mapped = _resolve_reasoning_effort(model, effort)
        if mapped is not None:
            params["reasoning_effort"] = mapped
    elif effort is None and compat.supports_reasoning_effort:
        if model.thinking_level_map:
            off_value = model.thinking_level_map.get("off")
            if isinstance(off_value, str):
                params["reasoning_effort"] = off_value


def build_params(
    model: ChatCompletionsModel,
    context: Context,
    compat: ResolvedCompat,
) -> dict[str, Any]:
    """Build the Chat Completions streaming request body (pre-hook)."""
    cache_retention = _resolve_cache_retention(model)
    source_messages = [item.message for item in context.items]
    messages = convert_messages(model, context.system_prompt, source_messages, compat)
    cache_control = _get_compat_cache_control(compat, cache_retention)

    params: dict[str, Any] = {
        "model": model.id,
        "messages": messages,
        "stream": True,
    }

    is_openai = "api.openai.com" in model.base_url
    prompt_cache_key = _clamp_openai_prompt_cache_key(
        model.session_id if cache_retention != "none" else None
    )
    if (is_openai and cache_retention != "none") or (
        cache_retention == "long" and compat.supports_long_cache_retention
    ):
        if prompt_cache_key is not None:
            params["prompt_cache_key"] = prompt_cache_key

    if cache_retention == "long" and compat.supports_long_cache_retention:
        params["prompt_cache_retention"] = "24h"

    if compat.supports_usage_in_streaming:
        params["stream_options"] = {"include_usage": True}

    if compat.supports_store:
        params["store"] = False

    if model.request_max_tokens is not None:
        if compat.max_tokens_field == "max_tokens":
            params["max_tokens"] = model.request_max_tokens
        else:
            params["max_completion_tokens"] = model.request_max_tokens

    if model.temperature is not None:
        params["temperature"] = model.temperature

    if context.tools:
        params["tools"] = convert_tools(list(context.tools), compat)
        if compat.zai_tool_stream:
            params["tool_stream"] = True
    elif has_tool_history(source_messages):
        # Anthropic-via-proxy requires the tools param when tool history exists.
        params["tools"] = []

    if cache_control:
        _apply_anthropic_cache_control(
            messages,
            params.get("tools") if isinstance(params.get("tools"), list) else None,
            cache_control,
        )

    if model.tool_choice is not None:
        params["tool_choice"] = model.tool_choice

    _apply_thinking(params, model, compat, model.reasoning_effort)

    if compat.openrouter_routing:
        params["provider"] = dict(compat.openrouter_routing)

    if "ai-gateway.vercel.sh" in model.base_url and compat.vercel_gateway_routing:
        routing = compat.vercel_gateway_routing
        gateway_options: dict[str, list[str]] = {}
        if routing.get("only"):
            gateway_options["only"] = list(routing["only"])
        if routing.get("order"):
            gateway_options["order"] = list(routing["order"])
        if gateway_options:
            params["providerOptions"] = {"gateway": gateway_options}

    return params

"""Token usage, cost accounting, and ``finish_reason`` mapping.

Python port of pi-ai's ``calculateCost``, ``parseChunkUsage``, and
``mapStopReason`` (the last lives inline in ``openai-completions.ts``).

Cost honors the Anthropic 2× rule for the long-cache-write split even though
most Chat Completions providers do not report ``cache_write_1h`` — the rate
card and accounting model are shared with the other APIs otter will support,
and a provider that *does* report it (e.g. Anthropic-via-proxy on a Chat
Completions endpoint) must be costed correctly.
"""

from __future__ import annotations

from typing import Any

from otter_ai import StopReason, Usage, UsageCost
from otter_ai_chat_completions.models import ChatCompletionsModel


def calculate_cost(model: ChatCompletionsModel, usage: Usage) -> UsageCost:
    """Mutate ``usage.cost`` in place and return it.

    Mirrors pi-ai: ``cache_write_1h`` is charged at 2× the input rate (the
    short-write remainder at the ``cache_write`` rate); the other buckets use
    their own rates. All rates are per-million tokens.
    """
    rate = model.cost
    long_write = usage.cache_write_1h or 0
    short_write = usage.cache_write - long_write
    cost = UsageCost(
        input=(rate.input / 1_000_000) * usage.input,
        output=(rate.output / 1_000_000) * usage.output,
        cache_read=(rate.cache_read / 1_000_000) * usage.cache_read,
        cache_write=(rate.cache_write * short_write + rate.input * 2 * long_write)
        / 1_000_000,
        total=0.0,
    )
    cost.total = cost.input + cost.output + cost.cache_read + cost.cache_write
    usage.cost = cost
    return cost


def parse_chunk_usage(raw: Any, model: ChatCompletionsModel) -> Usage:
    """Parse a Chat Completions chunk's ``usage`` object into a :class:`Usage`.

    Follows the documented OpenAI/OpenRouter semantics: ``cached_tokens`` is
    cache-read (hits); ``cache_write_tokens`` is a separate write count (do not
    subtract it from ``cached_tokens``). Some providers (e.g. Moonshot) place
    usage on the choice instead of the chunk — the caller falls back to that.
    ``cache_write_1h`` is never reported by Chat Completions providers, so it
    is left ``None`` here.
    """
    prompt_tokens = int(_get(raw, "prompt_tokens", 0) or 0)
    details = _get(raw, "prompt_tokens_details", {}) or {}
    cache_read_tokens = int(_get(details, "cached_tokens", 0) or 0)
    if cache_read_tokens == 0:
        cache_read_tokens = int(_get(raw, "prompt_cache_hit_tokens", 0) or 0)
    cache_write_tokens = int(_get(details, "cache_write_tokens", 0) or 0)
    input_tokens = max(0, prompt_tokens - cache_read_tokens - cache_write_tokens)
    output_tokens = int(_get(raw, "completion_tokens", 0) or 0)
    total = input_tokens + output_tokens + cache_read_tokens + cache_write_tokens
    usage = Usage(
        input=input_tokens,
        output=output_tokens,
        cache_read=cache_read_tokens,
        cache_write=cache_write_tokens,
        cache_write_1h=None,
        total_tokens=total,
        cost=UsageCost(
            input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0
        ),
    )
    calculate_cost(model, usage)
    return usage


def map_stop_reason(reason: Any) -> tuple[StopReason, str | None]:
    """Map a Chat Completions ``finish_reason`` onto an otter ``StopReason``.

    Returns ``(stop_reason, error_message)`` where ``error_message`` is set
    only when the provider reported a failure class (``content_filter``,
    ``network_error``, or an unknown value). The ``aborted`` stop reason is
    never produced here — it only arises from the cooperative-abort path.
    """
    if reason is None:
        return "stop", None
    if reason in ("stop", "end"):
        return "stop", None
    if reason == "length":
        return "length", None
    if reason in ("function_call", "tool_calls"):
        return "tool_use", None
    if reason == "content_filter":
        return "error", "Provider finish_reason: content_filter"
    if reason == "network_error":
        return "error", "Provider finish_reason: network_error"
    return "error", f"Provider finish_reason: {reason}"


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """``getattr``-style access on a dict or object, returning ``default`` if absent."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

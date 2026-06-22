"""Token usage, cost accounting, and ``finish_reason`` mapping."""

from __future__ import annotations

from typing import Any

import pytest
from _helpers import make_model

from otter_ai_chat_completions import ChatCompletionsCost
from otter_ai_chat_completions._usage import (
    calculate_cost,
    map_stop_reason,
    parse_chunk_usage,
)
from otter_ai_core import Usage, UsageCost


def _cost(**kwargs: Any) -> ChatCompletionsCost:
    defaults = {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0}
    defaults.update(kwargs)
    return ChatCompletionsCost(**defaults)


def _zero_cost_usage() -> UsageCost:
    return UsageCost(input=0, output=0, cache_read=0, cache_write=0, total=0)


def test_calculate_cost_basic() -> None:
    model = make_model()
    usage = Usage(
        input=1000,
        output=500,
        cache_read=200,
        cache_write=100,
        total_tokens=1800,
        cost=_zero_cost_usage(),
    )
    calculate_cost(model, usage)
    # input rate 2.5 / 1M * 1000 = 0.0025; output 10.0/1M * 500 = 0.005;
    # cache_read 1.25/1M * 200 = 0.00025; cache_write rate 0.
    assert usage.cost.input == pytest.approx(0.0025)
    assert usage.cost.output == pytest.approx(0.005)
    assert usage.cost.cache_read == pytest.approx(0.00025)
    assert usage.cost.cache_write == pytest.approx(0.0)
    assert usage.cost.total == pytest.approx(0.0025 + 0.005 + 0.00025)


def test_calculate_cost_anthropic_2x_for_long_write() -> None:
    # cache_write_1h is charged at 2x the *input* rate (not the cache_write rate).
    model = make_model(cost=_cost(input=5.0, cache_write=1.0))
    usage = Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=1000,  # 600 short + 400 long
        cache_write_1h=400,
        total_tokens=1000,
        cost=_zero_cost_usage(),
    )
    calculate_cost(model, usage)
    # short_write = 600 -> 1.0/1M * 600 = 0.0006
    # long_write  = 400 -> 5.0 * 2 / 1M * 400 = 0.004
    assert usage.cost.cache_write == pytest.approx(0.0006 + 0.004)


def test_parse_chunk_usage_standard_cached_tokens() -> None:
    model = make_model()
    raw = {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "prompt_tokens_details": {"cached_tokens": 30, "cache_write_tokens": 10},
    }
    usage = parse_chunk_usage(raw, model)
    assert usage.input == 60  # 100 - 30 cache_read - 10 cache_write
    assert usage.output == 50
    assert usage.cache_read == 30
    assert usage.cache_write == 10
    assert usage.cache_write_1h is None
    assert usage.total_tokens == 150
    assert usage.cost.total == pytest.approx(
        usage.cost.input
        + usage.cost.output
        + usage.cost.cache_read
        + usage.cost.cache_write
    )


def test_parse_chunk_usage_fallback_prompt_cache_hit_tokens() -> None:
    model = make_model()
    raw = {"prompt_tokens": 100, "completion_tokens": 0, "prompt_cache_hit_tokens": 25}
    usage = parse_chunk_usage(raw, model)
    assert usage.cache_read == 25
    assert usage.input == 75


@pytest.mark.parametrize(
    "finish_reason,expected",
    [
        (None, ("stop", None)),
        ("stop", ("stop", None)),
        ("end", ("stop", None)),
        ("length", ("length", None)),
        ("function_call", ("tool_use", None)),
        ("tool_calls", ("tool_use", None)),
    ],
)
def test_map_stop_reason_success_classes(
    finish_reason: object, expected: tuple[str, str | None]
) -> None:
    assert map_stop_reason(finish_reason) == expected


def test_map_stop_reason_content_filter_is_error() -> None:
    stop, message = map_stop_reason("content_filter")
    assert stop == "error"
    assert message == "Provider finish_reason: content_filter"


def test_map_stop_reason_unknown_is_error_with_message() -> None:
    stop, message = map_stop_reason("something_odd")
    assert stop == "error"
    assert message == "Provider finish_reason: something_odd"

"""Tests for the Chat Completions data model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from otter_ai_chat_completions import (
    ChatCompletionsCompat,
    ChatCompletionsCost,
    ChatCompletionsModel,
)


def _sample_model(**overrides: object) -> ChatCompletionsModel:
    base: dict[str, object] = {
        "id": "gpt-4o",
        "name": "GPT-4o",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "reasoning": False,
        "input_modalities": ["text", "image"],
        "context_window": 128_000,
        "max_tokens": 16_384,
        "cost": ChatCompletionsCost(
            input=2.5, output=10.0, cache_read=1.25, cache_write=0.0
        ),
    }
    base.update(overrides)
    return ChatCompletionsModel(**base)


def test_model_round_trips_json() -> None:
    model = _sample_model(
        api_key="sk-xxx",
        temperature=0.7,
        request_max_tokens=512,
        reasoning_effort="medium",
        compat=ChatCompletionsCompat(
            thinking_format="openai",
            supports_store=True,
            max_tokens_field="max_completion_tokens",
        ),
    )
    restored = ChatCompletionsModel.model_validate_json(model.model_dump_json())
    assert restored == model


def test_api_defaults_to_chat_completions() -> None:
    assert _sample_model().api == "chat-completions"


def test_extra_forbid_rejects_unknown_field() -> None:
    # Typo protection: ``max_token`` vs ``max_tokens`` must fail loud.
    with pytest.raises(ValidationError):
        _sample_model(max_token=512)


def test_model_copy_supports_per_call_mutation() -> None:
    model = _sample_model()
    chatty = model.model_copy(update={"temperature": 0.9})
    assert chatty.temperature == 0.9
    # Original is untouched.
    assert model.temperature is None


def test_compat_all_none_constructs() -> None:
    # The standard-defaults path: consumer leaves compat fully unset.
    compat = ChatCompletionsCompat()
    for field_name in ChatCompletionsCompat.model_fields:
        assert getattr(compat, field_name) is None


def test_model_without_compat_constructs() -> None:
    assert _sample_model().compat is None

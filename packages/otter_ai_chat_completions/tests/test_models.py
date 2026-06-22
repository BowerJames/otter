"""Tests for the Chat Completions data model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from otter_ai_chat_completions import (
    ChatCompletionsCompat,
    ChatCompletionsCost,
    ChatCompletionsModel,
    ChatTemplateKwargVar,
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


def test_cost_round_trips_json() -> None:
    cost = ChatCompletionsCost(input=2.5, output=10.0, cache_read=1.25, cache_write=0.0)
    restored = ChatCompletionsCost.model_validate_json(cost.model_dump_json())
    assert restored == cost


def test_cost_rejects_unknown_field() -> None:
    # ``extra="forbid"`` must reject typos on the cost submodel too.
    with pytest.raises(ValidationError):
        ChatCompletionsCost(
            input=2.5,
            output=10.0,
            cache_read=1.25,
            cache_write=0.0,
            currency="usd",  # type: ignore[call-arg]
        )


def test_compat_rejects_unknown_field() -> None:
    # ``extra="forbid"`` must reject typos on the compat submodel too.
    with pytest.raises(ValidationError):
        ChatCompletionsCompat(thinkingFormat="openai")  # type: ignore[call-arg]


def test_compat_round_trips_json() -> None:
    # Fully populate all 18 mixed-type optional fields so serialization is
    # exercised in one place (compat is otherwise only tested via the model).
    compat = ChatCompletionsCompat(
        supports_store=True,
        supports_developer_role=False,
        supports_reasoning_effort=True,
        supports_usage_in_streaming=False,
        max_tokens_field="max_tokens",
        requires_tool_result_name=True,
        requires_assistant_after_tool_result=False,
        requires_thinking_as_text=True,
        requires_reasoning_content_on_assistant_messages=True,
        thinking_format="chat-template",
        chat_template_kwargs={
            "enable_thinking": ChatTemplateKwargVar(var="thinking.enabled"),
            "effort": ChatTemplateKwargVar(var="thinking.effort", omit_when_off=True),
            "static": "value",
        },
        openrouter_routing={"only": ["anthropic"]},
        vercel_gateway_routing={"order": ["openai"]},
        zai_tool_stream=True,
        supports_strict_mode=False,
        cache_control_format="anthropic",
        send_session_affinity_headers=True,
        supports_long_cache_retention=False,
    )
    restored = ChatCompletionsCompat.model_validate_json(compat.model_dump_json())
    assert restored == compat


def test_compat_has_eighteen_fields() -> None:
    # Pin the public compat field set. ``chat_template_kwargs`` was added in #13
    # bringing the count from 17 to 18.
    assert len(ChatCompletionsCompat.model_fields) == 18


def test_chat_template_kwarg_var_round_trips() -> None:
    var = ChatTemplateKwargVar(var="thinking.effort", omit_when_off=True)
    restored = ChatTemplateKwargVar.model_validate_json(var.model_dump_json())
    assert restored == var


def test_chat_template_kwarg_var_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        ChatTemplateKwargVar(var="thinking.effort", omitWhenOff=True)  # type: ignore[call-arg]


def test_thinking_format_includes_chat_template() -> None:
    # The generic ``chat-template`` format was added in #13 alongside
    # ``chat_template_kwargs``.
    field = ChatCompletionsCompat.model_fields["thinking_format"]
    assert "chat-template" in str(field.annotation)

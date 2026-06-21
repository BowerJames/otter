"""Smoke tests: imports, options defaults, and seam placeholder behaviour."""

from __future__ import annotations

import asyncio

import pytest

import otter_ai_chat_completions as pkg
from otter_ai import Context, UserMessage
from otter_ai_chat_completions import (
    ChatCompletionsCost,
    ChatCompletionsHooks,
    ChatCompletionsModel,
    ChatCompletionsModelOptions,
    create_chat_completions_assistant_message_stream,
)


def _options() -> ChatCompletionsModelOptions:
    model = ChatCompletionsModel(
        id="gpt-4o",
        name="GPT-4o",
        provider="openai",
        base_url="https://api.openai.com/v1",
        reasoning=False,
        input_modalities=["text"],
        context_window=128_000,
        max_tokens=16_384,
        cost=ChatCompletionsCost(
            input=2.5, output=10.0, cache_read=1.25, cache_write=0.0
        ),
    )
    return ChatCompletionsModelOptions(model=model)


def test_public_api_imports() -> None:
    expected = {
        "ChatCompletionsModel",
        "ChatCompletionsCost",
        "ChatCompletionsCompat",
        "ChatCompletionsHooks",
        "ChatCompletionsModelOptions",
        "OnPayloadEvent",
        "OnResponseEvent",
        "OnPayloadHook",
        "OnResponseHook",
        "Payload",
        "create_chat_completions_assistant_message_stream",
    }
    missing = expected - set(pkg.__all__)
    assert not missing, f"missing exports: {missing}"


def test_options_defaults() -> None:
    options = _options()
    assert isinstance(options.hooks, ChatCompletionsHooks)
    assert options.hooks.on_payload is None
    assert options.hooks.on_response is None
    assert isinstance(options.abort_signal, asyncio.Event)
    assert not options.abort_signal.is_set()


def test_seam_is_callable_and_not_implemented() -> None:
    options = _options()
    context = Context(
        system_prompt="hi",
        messages=[UserMessage(role="user", content="hello", timestamp=0)],
    )
    with pytest.raises(NotImplementedError):
        create_chat_completions_assistant_message_stream(options, context)

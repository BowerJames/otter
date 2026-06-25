"""Smoke tests: imports, options defaults, and seam contract."""

from __future__ import annotations

import asyncio

import otter_ai_chat_completions as pkg
from otter_ai_chat_completions import (
    ChatCompletionsCost,
    ChatCompletionsHooks,
    ChatCompletionsModel,
    ChatCompletionsModelOptions,
    create_chat_completions_assistant_message_stream,
)
from otter_ai_core import Context, ContextItem, Stream, UserMessage


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
    # Every name advertised in ``__all__`` must actually resolve on the
    # package object (guards against an export being declared but never
    # imported, and covers the literal aliases + ``__version__``).
    assert pkg.__all__, "__all__ should not be empty"
    missing: list[str] = []
    for name in pkg.__all__:
        if not hasattr(pkg, name):
            missing.append(name)
    assert not missing, f"declared but not importable: {missing}"

    # ``__version__`` is the first entry of ``__all__``; assert it is a
    # non-empty string (the loop above only checks resolvability, not type).
    assert isinstance(pkg.__version__, str)
    assert pkg.__version__


def test_options_defaults() -> None:
    options = _options()
    assert isinstance(options.hooks, ChatCompletionsHooks)
    assert options.hooks.on_payload is None
    assert options.hooks.on_response is None


def test_options_defaults_are_independent() -> None:
    # The ``default_factory`` pattern must give each construction fresh
    # hooks — a shared-mutable default would alias hooks across instances.
    # Pin that contract.
    a = _options()
    b = _options()
    assert a.hooks is not b.hooks


async def test_seam_returns_stream_synchronously() -> None:
    # The seam is synchronous: it returns an ``AssistantMessageStream`` (a
    # ``Stream``) without raising, and schedules its producer via
    # ``asyncio.create_task``. With no API key the producer will emit an error
    # event — but the synchronous return contract is what we pin here.
    options = _options()
    context = Context(
        system_prompt="hi",
        items=[
            ContextItem(
                id="u1", message=UserMessage(role="user", content="hello", timestamp=0)
            )
        ],
    )
    stream = create_chat_completions_assistant_message_stream(options, context)
    assert isinstance(stream, Stream)
    # A producer task was scheduled and is tracked. Drain the stream to
    # completion (the no-API-key producer emits its error event and ends
    # itself) so the test neither leaks the task nor hangs.
    _ = [event async for event in stream]
    await asyncio.sleep(0)

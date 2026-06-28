"""Tests for the api stream-function registry."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from otter_ai_assistant_provider_stream import (
    DEFAULT_API,
    create_assistant_message_stream_by_provider,
    get_api_stream_fn,
    get_default_api_stream_fn,
    list_apis,
    register_api_stream_fn,
)
from otter_ai_assistant_provider_stream.types import (
    ModelProviderConfig,
    ModelProviderOptions,
)
from otter_ai_core import Context, create_stream
from otter_ai_core.assistant_message_stream import AssistantMessageStream


def _make_options(api: str = "custom-api") -> ModelProviderOptions:
    return ModelProviderOptions(
        model=ModelProviderConfig(
            model="gpt-4o", provider="openai", api=api, api_key="sk-test"
        )
    )


class TestBuiltInApi:
    def test_default_api_constant(self) -> None:
        assert DEFAULT_API == "chat-completions"

    def test_chat_completions_fn_registered(self) -> None:
        assert get_default_api_stream_fn() is not None
        assert "chat-completions" in list_apis()

    def test_chat_completions_fn_is_the_chat_completions_seam(self) -> None:
        from otter_ai_chat_completions import (
            create_chat_completions_assistant_message_stream,
        )

        assert (
            get_api_stream_fn("chat-completions")
            is create_chat_completions_assistant_message_stream
        )


class TestRuntimeRegistration:
    def test_register_custom_fn(self) -> None:
        def fn(
            _options: object, _context: Context, _abort: asyncio.Event
        ) -> AssistantMessageStream:
            raise AssertionError

        register_api_stream_fn("custom-api", fn)
        assert get_api_stream_fn("custom-api") is fn
        assert "custom-api" in list_apis()

    def test_get_unknown_returns_none(self) -> None:
        assert get_api_stream_fn("never-registered") is None

    def test_register_overwrites(self) -> None:
        def first(_o: object, _c: Context, _a: asyncio.Event) -> AssistantMessageStream:
            raise AssertionError

        def second(
            _o: object, _c: Context, _a: asyncio.Event
        ) -> AssistantMessageStream:
            raise AssertionError

        register_api_stream_fn("overwritable", first)
        register_api_stream_fn("overwritable", second)
        assert get_api_stream_fn("overwritable") is second


class TestDispatchUsesRegisteredFn:
    """The seam must invoke the api fn registered for options.model.api."""

    async def test_custom_fn_dispatched(self) -> None:
        seen: list[Context] = []

        def fake_fn(
            _options: object, context: Context, _abort: asyncio.Event
        ) -> AssistantMessageStream:
            seen.append(context)
            stream: AssistantMessageStream
            writer: object
            stream, writer = create_stream()
            writer.end()
            return stream

        register_api_stream_fn("custom-api", fake_fn)
        options = _make_options(api="custom-api")
        context = Context()

        returned = create_assistant_message_stream_by_provider(options, context)
        assert seen == [context]

        # The returned stream is the one the registered fn built (drains empty).
        events = [event async for event in returned]
        assert events == []

    def test_fn_type_is_callable_generic(self) -> None:
        # Sanity: the registry value is a plain callable.
        fn = get_default_api_stream_fn()
        assert isinstance(fn, Callable)  # type: ignore[arg-type]

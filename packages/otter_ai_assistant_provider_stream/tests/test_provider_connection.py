"""Tests for the provider-dispatch connection seam.

Covers option resolution (chat catalog lookup, env-key precedence,
thinking-level clamp + mapping; realtime catalog lookup), ``KnownApis``
routing, the never-raises contract, and end-to-end runs through both paths:
the chat path via the local adapter (faked httpx transport) and the realtime
path via a fake WebSocket.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from _provider_helpers import (
    FakeRealtimeWS,
    drive_connection,
    install_fake_realtime,
    install_fake_transport,
    simple_context,
    sse_response,
    start_connection,
)

from otter_ai_core import (
    Context,
    KnownApis,
    KnownProviders,
    ProviderModelOption,
    ThinkingLevel,
)
from otter_ai_core.model_connection import (
    ConnectionErrorEvent,
    ResponseCreate,
    ResponseErrorEvent,
)

# --------------------------------------------------------------------------- #
# Option factories
# --------------------------------------------------------------------------- #


def _chat_option(**overrides: Any) -> ProviderModelOption:
    base: dict[str, Any] = {
        "model": "glm-5.2",
        "provider": KnownProviders.ZAI,
        "api": KnownApis.ChatCompletion,
        "api_key": "sk-explicit",
    }
    base.update(overrides)
    return ProviderModelOption(**base)


def _realtime_option(**overrides: Any) -> ProviderModelOption:
    base: dict[str, Any] = {
        "model": "gpt-4o-realtime-preview",
        "provider": KnownProviders.OPEN_AI,
        "api": KnownApis.Realtime,
        "api_key": "sk-explicit",
    }
    base.update(overrides)
    return ProviderModelOption(**base)


# --------------------------------------------------------------------------- #
# Chat-completions resolution
# --------------------------------------------------------------------------- #


class TestChatResolution:
    def test_resolves_built_in_zai_model(self) -> None:
        from otter_ai_assistant_provider_stream.connection import (
            _resolve_chat_stream_fn,
        )

        stream_fn = _resolve_chat_stream_fn(_chat_option())
        assert callable(stream_fn)

    def test_unknown_model_raises(self) -> None:
        from otter_ai_assistant_provider_stream.connection import (
            _resolve_chat_stream_fn,
        )

        with pytest.raises(RuntimeError, match="No model registered"):
            _resolve_chat_stream_fn(_chat_option(model="no-such-model"))

    def test_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from otter_ai_assistant_provider_stream.connection import (
            _resolve_chat_stream_fn,
        )

        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="No API key"):
            _resolve_chat_stream_fn(_chat_option(api_key=None))

    def test_env_key_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Resolution surfaces the env key on the built model when no explicit
        # key is given (verified end-to-end below; here just ensure it resolves).
        from otter_ai_assistant_provider_stream.connection import (
            _resolve_chat_stream_fn,
        )

        monkeypatch.setenv("ZAI_API_KEY", "sk-from-env")
        # Should not raise.
        assert callable(_resolve_chat_stream_fn(_chat_option(api_key=None)))


# --------------------------------------------------------------------------- #
# Realtime resolution
# --------------------------------------------------------------------------- #


class TestRealtimeResolution:
    def test_resolves_built_in_realtime_model(self) -> None:
        from otter_ai_assistant_provider_stream.connection import (
            _resolve_realtime_model,
        )

        model = _resolve_realtime_model(_realtime_option())
        assert model.id == "gpt-4o-realtime-preview"
        assert model.provider == "openai"
        # Explicit key wins.
        assert model.api_key == "sk-explicit"

    def test_env_key_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from otter_ai_assistant_provider_stream.connection import (
            _resolve_realtime_model,
        )

        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        model = _resolve_realtime_model(_realtime_option(api_key=None))
        assert model.api_key == "sk-from-env"

    def test_missing_key_left_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A missing key is left for the realtime seam to encode (not raised).
        from otter_ai_assistant_provider_stream.connection import (
            _resolve_realtime_model,
        )

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        model = _resolve_realtime_model(_realtime_option(api_key=None))
        assert model.api_key is None

    def test_unknown_realtime_model_raises_catalog_miss(self) -> None:
        from otter_ai_assistant_provider_stream.connection import (
            _RealtimeCatalogMiss,
            _resolve_realtime_model,
        )

        with pytest.raises(_RealtimeCatalogMiss):
            _resolve_realtime_model(_realtime_option(model="no-such-realtime"))

    def test_thinking_level_ignored(self) -> None:
        from otter_ai_assistant_provider_stream.connection import (
            _resolve_realtime_model,
        )

        # Realtime has no thinking concept; the level must not affect resolution.
        model_a = _resolve_realtime_model(_realtime_option())
        model_b = _resolve_realtime_model(
            _realtime_option(thinking_level=ThinkingLevel.Off)
        )
        assert model_a.id == model_b.id


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #


class TestRouting:
    def test_chat_routes_to_chat_builder(self) -> None:
        from otter_ai_assistant_provider_stream import (
            get_model_connection_builder,
        )

        # The seam resolves the builder lazily; here we assert the registry
        # side. End-to-end routing is covered by the E2E tests below.
        assert get_model_connection_builder(KnownApis.ChatCompletion) is not None

    def test_realtime_routes_to_realtime_builder(self) -> None:
        from otter_ai_assistant_provider_stream import (
            get_model_connection_builder,
        )

        assert get_model_connection_builder(KnownApis.Realtime) is not None

    def test_unregistered_api_yields_connection_error(self) -> None:
        # ``Responses`` has no registered builder.
        option = ProviderModelOption(
            model="gpt-4o",
            provider=KnownProviders.OPEN_AI,
            api=KnownApis.Responses,
            api_key="sk",
        )
        events = asyncio.run(drive_connection(start_connection(option, Context()), []))
        assert len(events) == 1
        assert isinstance(events[0], ConnectionErrorEvent)
        assert "responses" in events[0].message


class TestAbortThreading:
    async def test_abort_threaded_to_dispatched_producer(self) -> None:
        # The seam forwards the caller's ``abort`` to the dispatched builder's
        # producer (its second argument), exactly as the old stream seam did.
        from otter_ai_assistant_provider_stream import (
            register_model_connection_builder,
        )
        from otter_ai_core import create_connection

        seen: list[object] = []

        def fake_builder(_options: ProviderModelOption) -> Any:
            def producer(_context: Context, abort: asyncio.Event) -> Any:
                seen.append(abort)
                conn: Any
                backend: Any
                conn, backend = create_connection()
                backend.end()
                return conn

            return producer

        register_model_connection_builder(KnownApis.Responses, fake_builder)
        option = ProviderModelOption(
            model="m",
            provider=KnownProviders.OPEN_AI,
            api=KnownApis.Responses,
            api_key="sk",
        )
        abort = asyncio.Event()
        await drive_connection(start_connection(option, Context(), abort), [])
        assert seen == [abort]


# --------------------------------------------------------------------------- #
# Never-raises contract
# --------------------------------------------------------------------------- #


class TestNeverRaises:
    async def test_chat_unknown_model_yields_error_event(self) -> None:
        events = await drive_connection(
            start_connection(_chat_option(model="no-such"), Context()),
            [ResponseCreate(type="response.create")],
        )
        types = [type(e).__name__ for e in events]
        assert "ResponseErrorEvent" in types
        err = next(e for e in events if isinstance(e, ResponseErrorEvent))
        assert err.partial.error_message is not None
        assert "No model registered" in err.partial.error_message

    async def test_chat_missing_key_yields_error_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        events = await drive_connection(
            start_connection(_chat_option(api_key=None), Context()),
            [ResponseCreate(type="response.create")],
        )
        err = next(e for e in events if isinstance(e, ResponseErrorEvent))
        assert err.partial.error_message is not None
        assert "No API key" in err.partial.error_message

    async def test_chat_error_event_carries_provenance(self) -> None:
        events = await drive_connection(
            start_connection(_chat_option(model="no-such"), Context()),
            [ResponseCreate(type="response.create")],
        )
        err = next(e for e in events if isinstance(e, ResponseErrorEvent))
        assert err.partial.provider == "zai"
        assert err.partial.model == "no-such"
        assert err.partial.stop_reason == "error"

    def test_realtime_unknown_model_yields_connection_error(self) -> None:
        events = asyncio.run(
            drive_connection(
                start_connection(_realtime_option(model="no-such"), Context()), []
            )
        )
        assert len(events) == 1
        assert isinstance(events[0], ConnectionErrorEvent)
        assert "realtime model" in events[0].message

    async def test_realtime_missing_key_yields_connection_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The realtime seam spawns its backend via ``asyncio.create_task``, so the
        # producer must be invoked inside a running loop (hence ``async def``).
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        events = await drive_connection(
            start_connection(_realtime_option(api_key=None), Context()), []
        )
        assert len(events) == 1
        assert isinstance(events[0], ConnectionErrorEvent)
        assert "API key" in events[0].message


# --------------------------------------------------------------------------- #
# End-to-end: chat path via the local adapter (faked httpx transport)
# --------------------------------------------------------------------------- #


def _sse_handler_factory(
    received: dict[str, Any],
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        received["auth"] = request.headers.get("authorization")
        received["body"] = json.loads(request.content.decode("utf-8"))
        return sse_response(
            [
                {"choices": [{"delta": {"content": "hi"}, "index": 0}]},
                {
                    "choices": [{"finish_reason": "stop", "index": 0}],
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 2,
                        "total_tokens": 7,
                    },
                },
            ]
        )

    return handler


class TestChatEndToEnd:
    async def test_runs_through_chat_completions_via_adapter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        received: dict[str, Any] = {}
        install_fake_transport(monkeypatch, _sse_handler_factory(received))

        events = await drive_connection(
            start_connection(
                _chat_option(api_key="sk-explicit", thinking_level=ThinkingLevel.Off),
                simple_context("hello"),
            ),
            [ResponseCreate(type="response.create")],
        )
        # Transport was hit with the resolved key.
        assert received["auth"] == "Bearer sk-explicit"
        types = [type(e).__name__ for e in events]
        assert "ResponseStartedEvent" in types
        assert "ResponseDoneEvent" in types
        # thinking_level=Off -> reasoning_effort omitted from the payload.
        assert "reasoning_effort" not in received["body"]

    async def test_env_key_reaches_transport(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ZAI_API_KEY", "sk-from-env")
        received: dict[str, Any] = {}
        install_fake_transport(monkeypatch, _sse_handler_factory(received))

        await drive_connection(
            start_connection(
                _chat_option(api_key=None, thinking_level=ThinkingLevel.Off),
                simple_context(),
            ),
            [ResponseCreate(type="response.create")],
        )
        assert received["auth"] == "Bearer sk-from-env"

    async def test_thinking_low_sends_reasoning_effort(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        received: dict[str, Any] = {}
        install_fake_transport(monkeypatch, _sse_handler_factory(received))

        await drive_connection(
            start_connection(
                _chat_option(api_key="sk-explicit", thinking_level=ThinkingLevel.Low),
                simple_context(),
            ),
            [ResponseCreate(type="response.create")],
        )
        # glm-5.2 supports low -> reasoning_effort reaches the payload. The
        # glm-5.2 ``thinking_level_map`` rewrites the wire value low -> high.
        assert received["body"]["reasoning_effort"] == "high"


# --------------------------------------------------------------------------- #
# End-to-end: realtime path via a fake WebSocket
# --------------------------------------------------------------------------- #


_RT_FRAMES: list[dict[str, Any]] = [
    {"type": "response.created", "response": {"id": "resp_1"}},
    {
        "type": "response.content_part.added",
        "part": {"type": "text", "text": ""},
    },
    {"type": "response.text.delta", "delta": "Hi"},
    {"type": "response.text.done", "text": "Hi"},
    {"type": "response.completed", "response": {"status": "completed"}},
]


class TestRealtimeEndToEnd:
    async def test_happy_path_drives_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeRealtimeWS()
        install_fake_realtime(monkeypatch, fake)

        conn = start_connection(_realtime_option(), Context())

        # Drive a response: send ResponseCreate, feed server frames, close.
        conn.send(ResponseCreate(type="response.create"))
        fake.feed(*_RT_FRAMES)
        fake.close_inbound()

        events = [e async for e in conn]

        # The opening session.update landed on the wire with the resolved model.
        types_sent = [f["type"] for f in fake.sent]
        assert types_sent[0] == "session.update"
        # A response.create frame was sent by the caller.
        assert "response.create" in types_sent
        # Server events were translated.
        names = {type(e).__name__ for e in events}
        assert "ResponseStartedEvent" in names
        assert "ResponseDoneEvent" in names

    async def test_resolved_model_used_for_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The fake ignores the URL, but we can assert the realtime seam was
        # reached (no ConnectionErrorEvent) for a known model + key.
        fake = FakeRealtimeWS()
        install_fake_realtime(monkeypatch, fake)

        conn = start_connection(_realtime_option(), Context())
        conn.send(ResponseCreate(type="response.create"))
        fake.feed(*_RT_FRAMES)
        fake.close_inbound()

        events = [e async for e in conn]
        assert not any(isinstance(e, ConnectionErrorEvent) for e in events)

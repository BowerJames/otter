"""Tests for the provider-dispatch seam.

Covers option resolution (catalog lookup, env-key precedence, thinking-level
clamp + mapping, overrides), passthrough of hooks/abort, the never-raises
contract, and an end-to-end run through the real chat-completions fn with a
faked httpx transport.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from _provider_helpers import (
    collect,
    install_fake_transport,
    simple_context,
    sse_response,
)

from otter_ai import (
    AssistantErrorEvent,
    AssistantMessageStream,
    Context,
)
from otter_ai_assistant_provider_stream import (
    create_assistant_message_stream_by_provider,
)
from otter_ai_assistant_provider_stream.stream import _resolve_options
from otter_ai_assistant_provider_stream.types import (
    ModelProviderConfig,
    ModelProviderOptions,
    ModelProviderOverrides,
)

# --------------------------------------------------------------------------- #
# Option resolution
# --------------------------------------------------------------------------- #


def _config(**overrides: Any) -> ModelProviderConfig:
    base: dict[str, Any] = {
        "model": "glm-5.2",
        "provider": "zai",
        "api_key": "sk-explicit",
    }
    base.update(overrides)
    return ModelProviderConfig(**base)


class TestOptionResolution:
    def test_resolves_built_in_zai_model(self) -> None:
        options = ModelProviderOptions(model=_config())
        resolved = _resolve_options(options)
        model = resolved.model
        assert model.id == "glm-5.2"
        assert model.provider == "zai"
        assert model.base_url == "https://api.z.ai/api/coding/paas/v4"
        # Explicit key wins.
        assert model.api_key == "sk-explicit"

    def test_env_key_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ZAI_API_KEY", "sk-from-env")
        options = ModelProviderOptions(
            model=ModelProviderConfig(model="glm-5.2", provider="zai")
        )
        resolved = _resolve_options(options)
        assert resolved.model.api_key == "sk-from-env"

    def test_explicit_key_beats_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ZAI_API_KEY", "sk-from-env")
        options = ModelProviderOptions(model=_config(api_key="sk-explicit"))
        assert _resolve_options(options).model.api_key == "sk-explicit"

    def test_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        options = ModelProviderOptions(
            model=ModelProviderConfig(model="glm-5.2", provider="zai")
        )
        with pytest.raises(RuntimeError, match="No API key"):
            _resolve_options(options)

    def test_unknown_model_raises(self) -> None:
        options = ModelProviderOptions(
            model=ModelProviderConfig(
                model="no-such-model", provider="zai", api_key="sk"
            )
        )
        with pytest.raises(RuntimeError, match="No model registered"):
            _resolve_options(options)


class TestThinkingLevel:
    def test_default_is_low(self) -> None:
        # The default thinking_level on ModelProviderConfig is "low".
        config = ModelProviderConfig(model="glm-5.2", provider="zai", api_key="sk")
        assert config.thinking_level == "low"

    def test_low_mapped_to_reasoning_effort(self) -> None:
        options = ModelProviderOptions(model=_config(thinking_level="low"))
        # glm-5.2 supports low, so effort is "low".
        assert _resolve_options(options).model.reasoning_effort == "low"

    def test_off_mapped_to_none(self) -> None:
        options = ModelProviderOptions(model=_config(thinking_level="off"))
        assert _resolve_options(options).model.reasoning_effort is None

    def test_unsupported_level_is_clamped(self) -> None:
        # glm-5.2 marks minimal as None -> clamps to low.
        options = ModelProviderOptions(model=_config(thinking_level="minimal"))
        assert _resolve_options(options).model.reasoning_effort == "low"

    def test_clamp_on_non_reasoning_model(self) -> None:
        # A non-reasoning openai model clamps any level to off -> None effort.
        # gpt-4o is non-reasoning in the catalog.
        options = ModelProviderOptions(
            model=ModelProviderConfig(
                model="gpt-4o", provider="openai", api_key="sk", thinking_level="high"
            )
        )
        assert _resolve_options(options).model.reasoning_effort is None


class TestOverrides:
    def test_direct_overrides_applied(self) -> None:
        options = ModelProviderOptions(
            model=_config(
                overrides=ModelProviderOverrides(
                    temperature=0.9, request_max_tokens=512
                )
            )
        )
        model = _resolve_options(options).model
        assert model.temperature == 0.9
        assert model.request_max_tokens == 512

    def test_base_url_override(self) -> None:
        options = ModelProviderOptions(
            model=_config(
                overrides=ModelProviderOverrides(base_url="https://proxy.test/v1")
            )
        )
        assert _resolve_options(options).model.base_url == "https://proxy.test/v1"

    def test_none_overrides_keep_catalog_values(self) -> None:
        options = ModelProviderOptions(model=_config())
        model = _resolve_options(options).model
        assert model.temperature is None
        assert model.base_url == "https://api.z.ai/api/coding/paas/v4"

    def test_compat_override_is_field_merged(self) -> None:
        from otter_ai_chat_completions import ChatCompletionsCompat

        # glm-5.2 catalog compat has thinking_format=zai, supports_developer_role=False,
        # supports_reasoning_effort=True. Override only one field.
        options = ModelProviderOptions(
            model=_config(
                overrides=ModelProviderOverrides(
                    compat=ChatCompletionsCompat(supports_reasoning_effort=False)
                )
            )
        )
        compat = _resolve_options(options).model.compat
        assert compat is not None
        # Overridden field wins.
        assert compat.supports_reasoning_effort is False
        # Non-overridden catalog fields are preserved.
        assert compat.thinking_format == "zai"
        assert compat.supports_developer_role is False

    def test_compat_override_applied_when_catalog_has_no_compat(self) -> None:
        # Regression: OpenAI models have catalog compat=None. A caller compat
        # override must still be applied (must not be silently dropped).
        from otter_ai_chat_completions import ChatCompletionsCompat

        options = ModelProviderOptions(
            model=ModelProviderConfig(
                model="gpt-4o",
                provider="openai",
                api_key="sk",
                thinking_level="off",
                overrides=ModelProviderOverrides(
                    compat=ChatCompletionsCompat(supports_store=True)
                ),
            )
        )
        compat = _resolve_options(options).model.compat
        assert compat is not None
        assert compat.supports_store is True
        # Non-overridden fields fall back to None (standard defaults).
        assert compat.thinking_format is None

    def test_overrides_do_not_carry_api_key(self) -> None:
        # api_key lives on ModelProviderConfig, not overrides (compile-time check
        # via the model — assert the field is genuinely absent).
        assert "api_key" not in ModelProviderOverrides.model_fields


class TestRuntimeHandlesPassthrough:
    def test_hooks_and_abort_signal_passed_through(self) -> None:
        from otter_ai_chat_completions import ChatCompletionsHooks

        hooks = ChatCompletionsHooks()
        abort = asyncio.Event()
        options = ModelProviderOptions(model=_config(), hooks=hooks, abort_signal=abort)
        resolved = _resolve_options(options)
        assert resolved.hooks is hooks
        assert resolved.abort_signal is abort

    def test_defaults_are_independent(self) -> None:
        a = ModelProviderOptions(model=_config())
        b = ModelProviderOptions(model=_config())
        assert a.hooks is not b.hooks
        assert a.abort_signal is not b.abort_signal


# --------------------------------------------------------------------------- #
# Never-raises contract
# --------------------------------------------------------------------------- #


async def _drain(stream: AssistantMessageStream) -> list[Any]:
    return [event async for event in stream]


class TestNeverRaises:
    async def test_unknown_model_yields_error_event(self) -> None:
        options = ModelProviderOptions(
            model=ModelProviderConfig(model="no-such", provider="zai", api_key="sk")
        )
        events = await _drain(
            create_assistant_message_stream_by_provider(options, Context())
        )
        assert len(events) == 1
        assert isinstance(events[0], AssistantErrorEvent)
        msg = events[0].error.error_message
        assert msg is not None and "No model registered" in msg

    async def test_missing_key_yields_error_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        options = ModelProviderOptions(
            model=ModelProviderConfig(model="glm-5.2", provider="zai")
        )
        events = await _drain(
            create_assistant_message_stream_by_provider(options, Context())
        )
        assert len(events) == 1
        assert isinstance(events[0], AssistantErrorEvent)
        msg = events[0].error.error_message
        assert msg is not None and "No API key" in msg

    async def test_unknown_api_yields_error_event(self) -> None:
        options = ModelProviderOptions(
            model=ModelProviderConfig(
                model="glm-5.2", provider="zai", api_key="sk", api="no-such-api"
            )
        )
        events = await _drain(
            create_assistant_message_stream_by_provider(options, Context())
        )
        assert len(events) == 1
        assert isinstance(events[0], AssistantErrorEvent)
        msg = events[0].error.error_message
        assert msg is not None and "no-such-api" in msg

    async def test_error_event_carries_provenance(self) -> None:
        options = ModelProviderOptions(
            model=ModelProviderConfig(model="no-such", provider="zai", api_key="sk")
        )
        events = await _drain(
            create_assistant_message_stream_by_provider(options, Context())
        )
        assert isinstance(events[0], AssistantErrorEvent)
        err = events[0].error
        assert err.provider == "zai"
        assert err.model == "no-such"
        assert err.stop_reason == "error"


# --------------------------------------------------------------------------- #
# End-to-end through the real chat-completions fn (faked transport)
# --------------------------------------------------------------------------- #


def _sse_handler_factory(
    received: dict[str, Any],
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        # Record the auth header + request body so tests can assert the
        # resolved options reached the transport.
        received["auth"] = request.headers.get("authorization")
        body = json.loads(request.content.decode("utf-8"))
        received["body"] = body
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


class TestEndToEnd:
    async def test_runs_through_chat_completions_fn(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        received: dict[str, Any] = {}
        install_fake_transport(monkeypatch, _sse_handler_factory(received))

        options = ModelProviderOptions(
            model=_config(api_key="sk-explicit", thinking_level="off")
        )
        stream = create_assistant_message_stream_by_provider(
            options, simple_context("hello")
        )

        events = await collect(stream)
        # Transport was hit with the resolved key.
        assert received["auth"] == "Bearer sk-explicit"
        # The stream produced at least start + done.
        types = [type(e).__name__ for e in events]
        assert "AssistantStartEvent" in types
        assert "AssistantDoneEvent" in types

    async def test_overrides_reach_transport(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        received: dict[str, Any] = {}
        install_fake_transport(monkeypatch, _sse_handler_factory(received))

        options = ModelProviderOptions(
            model=_config(
                api_key="sk-explicit",
                thinking_level="off",
                overrides=ModelProviderOverrides(
                    temperature=0.42, request_max_tokens=123
                ),
            )
        )
        await collect(
            create_assistant_message_stream_by_provider(options, simple_context())
        )
        body = received["body"]
        assert body["temperature"] == 0.42
        assert body["max_completion_tokens"] == 123

    async def test_env_key_reaches_transport(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ZAI_API_KEY", "sk-from-env")
        received: dict[str, Any] = {}
        install_fake_transport(monkeypatch, _sse_handler_factory(received))

        options = ModelProviderOptions(
            model=ModelProviderConfig(
                model="glm-5.2", provider="zai", thinking_level="off"
            )
        )
        await collect(
            create_assistant_message_stream_by_provider(options, simple_context())
        )
        assert received["auth"] == "Bearer sk-from-env"

    async def test_abort_signal_passed_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No transport needed: assert the abort signal object is the same one
        # the inner options carry.
        abort = asyncio.Event()
        options = ModelProviderOptions(model=_config(api_key="sk"), abort_signal=abort)
        resolved = _resolve_options(options)
        assert resolved.abort_signal is abort

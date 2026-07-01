"""Tests for the connection-builder registry (keyed on ``KnownApis``)."""

from __future__ import annotations

from otter_ai_assistant_provider_stream import (
    get_model_connection_builder,
    list_model_connection_builders,
    register_model_connection_builder,
)
from otter_ai_assistant_provider_stream.connection_registry import (
    clear_model_connection_builders,
)
from otter_ai_core import KnownApis, ProviderModelOption
from otter_ai_core.model_connection import ModelConnectionFn


def _builder(_options: ProviderModelOption) -> ModelConnectionFn:
    def _fn(_context: object, _abort: object) -> object:  # noqa: ARG001
        raise NotImplementedError

    return _fn  # type: ignore[return-value]


class TestBuiltInBuilders:
    def test_chat_completions_and_realtime_registered_on_import(self) -> None:
        apis = set(list_model_connection_builders())
        assert {KnownApis.ChatCompletion, KnownApis.Realtime}.issubset(apis)

    def test_chat_completions_builder_present(self) -> None:
        assert get_model_connection_builder(KnownApis.ChatCompletion) is not None

    def test_realtime_builder_present(self) -> None:
        assert get_model_connection_builder(KnownApis.Realtime) is not None

    def test_responses_has_no_builder(self) -> None:
        assert get_model_connection_builder(KnownApis.Responses) is None


class TestRuntimeRegistration:
    def test_register_and_get(self) -> None:
        register_model_connection_builder(KnownApis.Responses, _builder)
        assert get_model_connection_builder(KnownApis.Responses) is _builder

    def test_register_overwrites(self) -> None:
        register_model_connection_builder(KnownApis.Responses, _builder)

        def another(_options: ProviderModelOption) -> ModelConnectionFn:
            def _fn(_context: object, _abort: object) -> object:  # noqa: ARG001
                raise NotImplementedError

            return _fn  # type: ignore[return-value]

        register_model_connection_builder(KnownApis.Responses, another)
        assert get_model_connection_builder(KnownApis.Responses) is another

    def test_clear_removes_every_builder(self) -> None:
        clear_model_connection_builders()
        assert list_model_connection_builders() == []
        # ``reset()`` (autouse fixture) re-seeds after this test.

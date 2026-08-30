from collections.abc import Callable
from typing import cast

import pytest

from otter_ai_core.abstractions import AgentTool, Model
from otter_ai_core.model_registry import ModelRegistry, UnknownModelError


class _RecordingFactory:
    """Stand-in for the registered fns (`_ProviderFn` / `_CustomModelFn`)
    that records every invocation and returns a fixed sentinel factory.
    The sentinel is opaque: the registry returns it without ever invoking
    it, so identity comparison is the only thing tests need."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.factory = cast(Callable[[str, list[AgentTool]], Model], object())

    def __call__(self, *args: str) -> Callable[[str, list[AgentTool]], Model]:
        self.calls.append(args)
        return self.factory


def test_empty_registry_raises_for_provider_lookup() -> None:
    registry = ModelRegistry()

    with pytest.raises(UnknownModelError):
        registry.get_model("openai", "gpt-4o", "api-key-1")


def test_empty_registry_raises_for_custom_model_lookup() -> None:
    registry = ModelRegistry()

    with pytest.raises(UnknownModelError):
        registry.get_model(None, "gpt-4o", "api-key-1")


def test_provider_resolution_invokes_fn_with_model_and_api_key() -> None:
    registry = ModelRegistry()
    provider = _RecordingFactory()
    registry.add_provider("openai", provider)

    resolved = registry.get_model("openai", "gpt-4o", "api-key-1")

    assert resolved is provider.factory
    assert provider.calls == [("gpt-4o", "api-key-1")]


def test_custom_model_resolution_invokes_fn_with_api_key() -> None:
    registry = ModelRegistry()
    custom_model = _RecordingFactory()
    registry.add_custom_model("gpt-4o", custom_model)

    resolved = registry.get_model(None, "gpt-4o", "api-key-1")

    assert resolved is custom_model.factory
    assert custom_model.calls == [("api-key-1",)]


def test_provider_lookup_does_not_fall_back_to_custom_models() -> None:
    registry = ModelRegistry()
    custom_model = _RecordingFactory()
    registry.add_custom_model("gpt-4o", custom_model)

    with pytest.raises(UnknownModelError):
        registry.get_model("openai", "gpt-4o", "api-key-1")

    assert custom_model.calls == []


def test_custom_model_lookup_does_not_fall_back_to_providers() -> None:
    registry = ModelRegistry()
    provider = _RecordingFactory()
    registry.add_provider("openai", provider)

    with pytest.raises(UnknownModelError):
        registry.get_model(None, "gpt-4o", "api-key-1")

    assert provider.calls == []


def test_reregistered_provider_replaces_previous() -> None:
    registry = ModelRegistry()
    first = _RecordingFactory()
    second = _RecordingFactory()
    registry.add_provider("openai", first)
    registry.add_provider("openai", second)

    resolved = registry.get_model("openai", "gpt-4o", "api-key-1")

    assert resolved is second.factory
    assert first.calls == []
    assert second.calls == [("gpt-4o", "api-key-1")]


def test_reregistered_custom_model_replaces_previous() -> None:
    registry = ModelRegistry()
    first = _RecordingFactory()
    second = _RecordingFactory()
    registry.add_custom_model("gpt-4o", first)
    registry.add_custom_model("gpt-4o", second)

    resolved = registry.get_model(None, "gpt-4o", "api-key-1")

    assert resolved is second.factory
    assert first.calls == []
    assert second.calls == [("api-key-1",)]


def test_keys_are_matched_exactly() -> None:
    registry = ModelRegistry()
    provider = _RecordingFactory()
    custom_model = _RecordingFactory()
    registry.add_provider("openai", provider)
    registry.add_custom_model("gpt-4o", custom_model)

    with pytest.raises(UnknownModelError):
        registry.get_model("OpenAI", "gpt-4o", "api-key-1")
    with pytest.raises(UnknownModelError):
        registry.get_model(None, "GPT-4O", "api-key-1")

    resolved = registry.get_model("openai", "GPT-4O", "api-key-1")

    assert resolved is provider.factory
    assert provider.calls == [("GPT-4O", "api-key-1")]
    assert custom_model.calls == []


def test_unknown_model_error_names_missing_key_and_path() -> None:
    registry = ModelRegistry()
    registry.add_provider("anthropic", _RecordingFactory())

    with pytest.raises(UnknownModelError, match="openai"):
        registry.get_model("openai", "gpt-4o", "api-key-1")
    with pytest.raises(UnknownModelError, match="gpt-4o"):
        registry.get_model(None, "gpt-4o", "api-key-1")

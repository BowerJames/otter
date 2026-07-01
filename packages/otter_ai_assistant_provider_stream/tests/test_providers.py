"""Tests for the provider-config registry."""

from __future__ import annotations

from otter_ai_assistant_provider_stream import (
    BUILT_IN_PROVIDERS,
    get_provider,
    list_providers,
    register_provider,
    unregister_provider,
)
from otter_ai_assistant_provider_stream.types import ProviderConfig


class TestBuiltInProviders:
    def test_built_in_providers_constant(self) -> None:
        assert BUILT_IN_PROVIDERS == ["zai", "openai"]

    def test_built_in_providers_registered_on_import(self) -> None:
        names = set(list_providers())
        assert {"openai", "zai"}.issubset(names)

    def test_openai_config(self) -> None:
        config = get_provider("openai")
        assert config is not None
        assert config.env_key == "OPENAI_API_KEY"

    def test_zai_config(self) -> None:
        config = get_provider("zai")
        assert config is not None
        assert config.env_key == "ZAI_API_KEY"


class TestRuntimeRegistration:
    def test_register_and_get(self) -> None:
        config = ProviderConfig(name="custom", env_key="CUSTOM")
        register_provider(config)
        assert get_provider("custom") is config

    def test_unregister(self) -> None:
        register_provider(ProviderConfig(name="temp"))
        assert get_provider("temp") is not None
        unregister_provider("temp")
        assert get_provider("temp") is None

    def test_unregister_absent_is_noop(self) -> None:
        # Should not raise.
        unregister_provider("never-existed")

    def test_register_overwrites(self) -> None:
        register_provider(ProviderConfig(name="x", env_key="OLD"))
        register_provider(ProviderConfig(name="x", env_key="NEW"))
        overwritten = get_provider("x")
        assert overwritten is not None
        assert overwritten.env_key == "NEW"

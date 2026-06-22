"""Tests for env-var API-key resolution."""

from __future__ import annotations

import pytest

from otter_ai_assistant_provider_stream import (
    find_env_keys,
    get_env_api_key,
    register_provider,
)
from otter_ai_assistant_provider_stream.types import ProviderConfig


class TestBuiltInEnvKeys:
    def test_openai_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        assert find_env_keys("openai") == ["OPENAI_API_KEY"]
        assert get_env_api_key("openai") == "sk-openai"

    def test_zai_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ZAI_API_KEY", "sk-zai")
        assert find_env_keys("zai") == ["ZAI_API_KEY"]
        assert get_env_api_key("zai") == "sk-zai"

    def test_unset_env_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        assert find_env_keys("openai") is None
        assert get_env_api_key("openai") is None


class TestRegisteredProviderEnvKey:
    def test_registered_provider_env_key_consulted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        register_provider(ProviderConfig(name="custom", env_key="CUSTOM_API_KEY"))
        monkeypatch.setenv("CUSTOM_API_KEY", "sk-custom")
        assert get_env_api_key("custom") == "sk-custom"

    def test_registered_provider_without_env_key(self) -> None:
        register_provider(ProviderConfig(name="nokey"))
        assert find_env_keys("nokey") is None
        assert get_env_api_key("nokey") is None

    def test_unknown_provider_returns_none(self) -> None:
        assert find_env_keys("totally-unknown") is None
        assert get_env_api_key("totally-unknown") is None

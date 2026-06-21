"""Tests for the model-catalog registry."""

from __future__ import annotations

from _provider_helpers import model_kwargs

from otter_ai_assistant_provider_stream import (
    all_models,
    get_model,
    list_models,
    register_model,
)
from otter_ai_chat_completions import ChatCompletionsModel


class TestBuiltInCatalog:
    def test_openai_models_loaded(self) -> None:
        models = list_models("openai")
        assert len(models) > 0
        # Every entry is chat-completions, standard base URL, no compat.
        for model in models:
            assert model.provider == "openai"
            assert model.api == "chat-completions"
            assert model.base_url == "https://api.openai.com/v1"
            assert model.compat is None  # standard defaults

    def test_zai_models_loaded(self) -> None:
        models = list_models("zai")
        assert len(models) > 0
        for model in models:
            assert model.provider == "zai"
            assert model.base_url == "https://api.z.ai/api/coding/paas/v4"
            assert model.compat is not None
            assert model.compat.thinking_format == "zai"
            assert model.compat.supports_developer_role is False

    def test_glm52_specific_metadata(self) -> None:
        glm52 = get_model("zai", "glm-5.2")
        assert glm52 is not None
        assert glm52.reasoning is True
        assert glm52.thinking_level_map == {
            "minimal": None,
            "low": "high",
            "medium": "high",
            "high": "high",
            "xhigh": "max",
        }
        assert glm52.compat is not None
        assert glm52.compat.supports_reasoning_effort is True
        assert glm52.compat.zai_tool_stream is True

    def test_glm45_family_excludes_tool_stream(self) -> None:
        glm45 = get_model("zai", "glm-4.5-air")
        assert glm45 is not None
        assert glm45.compat is not None
        assert glm45.compat.zai_tool_stream is None

    def test_generated_entries_round_trip_json(self) -> None:
        # Every built-in catalog entry must JSON-round-trip (Context-style).
        for model in all_models():
            restored = ChatCompletionsModel.model_validate_json(model.model_dump_json())
            assert restored == model


class TestRuntimeRegistration:
    def test_register_and_get(self) -> None:
        model = ChatCompletionsModel(**model_kwargs(id="custom-1"))
        register_model(model)
        assert get_model("test-provider", "custom-1") is model

    def test_get_unknown_returns_none(self) -> None:
        assert get_model("test-provider", "missing") is None

    def test_register_overwrites(self) -> None:
        first = ChatCompletionsModel(**model_kwargs(id="dup"))
        second = ChatCompletionsModel(**model_kwargs(id="dup", name="Other"))
        register_model(first)
        register_model(second)
        assert get_model("test-provider", "dup") is second

    def test_list_models_scoped_to_provider(self) -> None:
        register_model(ChatCompletionsModel(**model_kwargs(id="a")))
        register_model(ChatCompletionsModel(**model_kwargs(id="b", provider="other")))
        ids = {m.id for m in list_models("test-provider")}
        assert ids == {"a"}
